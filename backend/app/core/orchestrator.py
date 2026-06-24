"""
Session management and background job execution.

Architecture principles (robust version):
- Background thread ONLY executes science steps. Never calls LLM.
- LLM is ONLY called from synchronous API request handlers.
- Each plan step is isolated — one step failing never crashes the job.
- Job completion is signalled via a dedicated flag, not inferred.
- Session state mutations are always done under the session lock.
"""
import json
import threading
import time
import uuid
from typing import Dict

from app.core.database import ensure_db, init_db, query_database
from app.core.llm import _SYSTEM_PROMPT_CONTENT, llm_plan
from app.core.lab import advance_to_next_day
from app.core.models import (
    AgentStateModel,
    ArtifactModel,
    EquipmentStatusModel,
    SessionModel,
)
from app.core.tools import (
    build_dynamic_timeline,
    build_execution_plan_from_tool_calls,
    execute_plan_step,
)

SESSIONS:      Dict[str, SessionModel]    = {}
SESSION_LOCKS: Dict[str, threading.Lock] = {}


def _lock_for(session_id: str) -> threading.Lock:
    if session_id not in SESSION_LOCKS:
        SESSION_LOCKS[session_id] = threading.Lock()
    return SESSION_LOCKS[session_id]


def _welcome_message() -> dict:
    return {
        "role": "assistant",
        "content": (
            "Welcome to **MAESTRO v3** — your agentic scientific orchestrator.\n\n"
            "You can:\n"
            "- Design and run optimisation campaigns\n"
            "- Upload a paper PDF for reproduction\n"
            "- Query your experimental results\n"
            "- Add tools to your virtual lab\n\n"
            "What would you like to explore today?"
        ),
    }


# ── Session lifecycle ─────────────────────────────────────────────────────────

def create_session() -> SessionModel:
    ensure_db()
    session_id  = str(uuid.uuid4())
    agent_state = AgentStateModel(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT_CONTENT},
            _welcome_message(),
        ],
    )
    session = SessionModel(
        session_id=session_id,
        agent_state=agent_state,
        current_mission="Awaiting scientific instruction.",
    )
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> SessionModel:
    if session_id not in SESSIONS:
        raise KeyError(f"Unknown session_id: {session_id}")
    return SESSIONS[session_id]


def reset_session(session_id: str) -> SessionModel:
    init_db()
    SESSIONS.pop(session_id, None)
    return create_session()


# ── User message handling ─────────────────────────────────────────────────────

def post_user_message(session_id: str, text: str) -> SessionModel:
    """
    Handle a user message. This is called from the API request thread.
    LLM calls are safe here — they block the request, not a background thread.
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        session.equipment_status.llm = True
        session.current_activity     = "Thinking..."
        session.agent_state.messages.append({"role": "user", "content": text})
        session.current_mission = text

    # LLM call outside lock — it's slow but only blocks this request thread
    llm_plan(session)

    with lock:
        session.equipment_status.llm = False
        session.current_activity     = None

    return session


# ── Live event consumption ────────────────────────────────────────────────────

def _consume_one_live_event(session: SessionModel):
    """
    Pop one event from the queue and update session UI state.
    Must be called under the session lock.
    """
    if not session.live_event_queue:
        return

    event = session.live_event_queue.pop(0)
    session.current_activity     = event.message
    session.background_job_label = event.message
    session.activity_log.append(f"[{event.category.upper()}] {event.message}")
    session.activity_log = session.activity_log[-20:]

    # Update equipment status to animate the correct digital twin node
    session.equipment_status = EquipmentStatusModel()
    eq_map = {
        "llm":       "llm",
        "optimiser": "optimiser",
        "sampler":   "sampler",
        "tester":    "tester",
        "memory":    "memory",
        "knowledge": "knowledge",
        "reporting": "reporting",
    }
    eq_key = eq_map.get(event.equipment or "")
    if eq_key:
        setattr(session.equipment_status, eq_key, True)


# ── Background job runner ─────────────────────────────────────────────────────

def _run_background_job(session_id: str):
    """
    Worker thread: executes the approved plan step by step.

    Design principles:
    1. Never calls LLM — avoids timeout/500 errors in background thread
    2. Each step is wrapped in try/except — one bad step never kills the job
    3. Always sets background_job_active=False on exit (success OR failure)
    4. Uses a dedicated completion flag so WebSocket can signal frontend cleanly
    5. Lock is held only for state mutations, not for slow I/O
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    def _mark_complete(success: bool, error_msg: str = ""):
        """Atomically mark the job as done and clean up UI state."""
        with lock:
            session.background_job_active  = False
            session.background_job_status  = "completed" if success else "failed"
            session.background_job_label   = None
            session.current_activity       = None
            session.equipment_status       = EquipmentStatusModel()

            if not success:
                session.background_job_error = error_msg
                session.agent_state.messages.append({
                    "role": "assistant",
                    "content": (
                        f"⚠️ The workflow stopped due to an error.\n\n"
                        f"**Details:** `{error_msg}`\n\n"
                        f"Any results collected before the error have been saved. "
                        f"You can ask me to continue or reset and try again."
                    ),
                })
            else:
                # Build completion summary from results — no LLM call needed
                results  = session.agent_state.results_store
                n_evals  = sum(len(r.get("X", [])) for r in results)
                n_fails  = sum(r.get("failed_samples", 0) for r in results)
                best_e   = max(
                    (r.get("best_energy") or 0.0 for r in results),
                    default=0.0,
                )
                powers_done = [
                    f"{int(r['power_W'])}W" for r in results if r.get("X")
                ]

                session.agent_state.messages.append({
                    "role": "assistant",
                    "content": (
                        f"✅ **Workflow complete.**\n\n"
                        f"| Metric | Value |\n"
                        f"|--------|-------|\n"
                        f"| Evaluations | {n_evals} |\n"
                        f"| Best specific energy | {best_e:.2f} Wh/kg |\n"
                        f"| Failed samples | {n_fails} |\n"
                        f"| Power levels completed | {', '.join(powers_done) or 'none'} |\n\n"
                        f"Ask me to **generate a summary figure**, "
                        f"**analyse the results**, or **continue tomorrow**."
                    ),
                })

    try:
        while True:
            # ── Tick: one unit of work per iteration ──────────────────────────
            with lock:
                has_events = bool(session.live_event_queue)
                has_steps  = session.background_job_index < len(session.background_job_plan)

            if has_events:
                with lock:
                    _consume_one_live_event(session)

            elif has_steps:
                # Read step outside lock so we don't hold it during execution
                with lock:
                    step  = session.background_job_plan[session.background_job_index]
                    session.background_job_label  = step.get("kind", "running")
                    session.background_job_status = "running"

                # Execute step — this is where slow I/O happens (BO, DB writes)
                # Isolated in try/except so one bad step doesn't kill the job
                try:
                    result = execute_plan_step(session, step, query_database)
                    with lock:
                        session.agent_state.last_tool_result = result
                        session.background_job_index += 1
                except Exception as step_err:
                    with lock:
                        session.activity_log.append(
                            f"[WARNING] Step '{step.get('kind')}' error: {step_err}"
                        )
                        session.activity_log = session.activity_log[-20:]
                        session.background_job_index += 1  # skip bad step, continue

            else:
                # No events, no steps left → job is done
                _mark_complete(success=True)
                break

            time.sleep(0.25)

    except Exception as fatal_err:
        # Truly unexpected error (e.g. memory corruption, import error)
        _mark_complete(success=False, error_msg=f"{type(fatal_err).__name__}: {fatal_err}")


# ── Workflow confirmation ─────────────────────────────────────────────────────

def confirm_pending(session_id: str, proceed: bool) -> SessionModel:
    """
    Called from the API request thread when user approves or aborts a workflow.
    If proceeding, spawns the background job thread.
    If aborting, calls LLM synchronously (safe — we're in a request thread).
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        if not session.agent_state.awaiting_confirmation:
            return session

    if proceed:
        with lock:
            plan = build_execution_plan_from_tool_calls(
                session, session.agent_state.pending_tool_calls
            )
            session.background_job_plan        = plan
            session.background_job_index       = 0
            session.background_job_status      = "running"
            session.background_job_active      = True
            session.background_job_label       = "Initialising..."
            session.background_job_error       = None
            session.live_event_queue           = []
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []

        # Spawn daemon thread — dies automatically if the server dies
        t = threading.Thread(
            target=_run_background_job,
            args=(session_id,),
            daemon=True,
            name=f"maestro-job-{session_id[:8]}",
        )
        t.start()

    else:
        # Abort path — inject tool rejection messages then call LLM
        # This is safe because we're in the API request thread
        with lock:
            for tc in session.agent_state.pending_tool_calls:
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         tc["function"]["name"],
                    "content":      json.dumps({
                        "status":  "abort",
                        "message": "User aborted this workflow.",
                    }),
                })
            session.agent_state.messages.append({
                "role": "user", "content": "abort"
            })
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []
            session.equipment_status.llm              = True

        llm_plan(session)  # Safe — request thread

        with lock:
            session.equipment_status.llm = False

    return session


# ── Day management ────────────────────────────────────────────────────────────

def next_day(session_id: str) -> SessionModel:
    session = get_session(session_id)
    advance_to_next_day(session)
    return session


# ── Artifacts ─────────────────────────────────────────────────────────────────

def register_artifact(session: SessionModel, name: str, kind: str, path: str):
    session.artifacts.append(ArtifactModel(name=name, kind=kind, path=path))
    session.artifacts = session.artifacts[-20:]


# ── State serialisation ───────────────────────────────────────────────────────

def session_state_payload(session: SessionModel) -> dict:
    """Serialise the full session state for the frontend."""
    return {
        "session_id":                 session.session_id,
        "messages":                   session.agent_state.messages,
        "results_store":              session.agent_state.results_store,
        "awaiting_confirmation":      session.agent_state.awaiting_confirmation,
        "pending_tool_calls":         session.agent_state.pending_tool_calls,
        "last_tool_result":           session.agent_state.last_tool_result,
        "last_tools_used":            session.agent_state.last_tools_used,
        "virtual_clock_minutes":      session.virtual_clock_minutes,
        "virtual_day_index":          session.virtual_day_index,
        "outstanding_tasks":          session.outstanding_tasks,
        "show_plotter_image":         session.show_plotter_image,
        "active_document_id":         session.active_document_id,
        "extracted_campaign":         (
            session.extracted_campaign.model_dump()
            if session.extracted_campaign else None
        ),
        "equipment_status":           session.equipment_status.model_dump(),
        "current_activity":           session.current_activity,
        "activity_log":               session.activity_log,
        "current_mission":            session.current_mission,
        "artifacts":                  [a.model_dump() for a in session.artifacts],
        "background_job_active":      session.background_job_active,
        "background_job_label":       session.background_job_label,
        "background_job_error":       session.background_job_error,
        "background_job_status":      session.background_job_status,
        "background_job_index":       session.background_job_index,
        "background_job_plan_length": len(session.background_job_plan),
        "timeline":                   build_dynamic_timeline(session),
    }