"""
Session management and background job execution.
Robust version: LLM never called in background thread.
Each plan step isolated — one failure never crashes the job.
"""
from __future__ import annotations

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
    ExecutionEvent, 
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
            "- Add tools to your virtual lab via the Lab Builder\n\n"
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
    """Called from API request thread — LLM call is safe here."""
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        session.agent_state.messages.append({"role": "user", "content": text})
        session.current_mission      = text
        session.equipment_status     = EquipmentStatusModel(llm=True)
        session.current_activity     = "Thinking..."
        session.live_event_queue.append(ExecutionEvent(
            event_type="llm_thinking",
            message="Thinking...",
            equipment="llm",
            category="planning",
            payload={},
        ))

    llm_plan(session)

    # Auto-approve feasibility checks — read-only, no user approval needed
    # Only run_extracted_campaign needs explicit user approval
    if session.agent_state.awaiting_confirmation:
        pending_names = [
            tc["function"]["name"]
            for tc in session.agent_state.pending_tool_calls
        ]
        all_feasibility = all(
            n == "extract_and_check_feasibility"
            for n in pending_names
        )
        if all_feasibility:
            pending_calls = list(session.agent_state.pending_tool_calls)

            with lock:
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []
                session.equipment_status = EquipmentStatusModel(knowledge=True)
                session.current_activity = "Checking feasibility..."

            for tc in pending_calls:
                args = {}
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    pass
                case_name = args.get("case_name", "Case Study")

                # Required by OpenAI: tool_calls must be followed by tool response
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         tc["function"]["name"],
                    "content":      json.dumps({
                        "status":    "running",
                        "case_name": case_name,
                    }),
                })

                step = {"kind": "extract_feasibility", "case_name": case_name}
                try:
                    execute_plan_step(session, step, query_database)
                except Exception as e:
                    session.agent_state.messages.append({
                        "role":    "assistant",
                        "content": f"Error during feasibility check: `{e}`",
                    })

            with lock:
                session.equipment_status = EquipmentStatusModel()
                session.current_activity = None

    with lock:
        session.equipment_status = EquipmentStatusModel()
        session.current_activity = None
        session.live_event_queue.append(ExecutionEvent(
            event_type="llm_done",
            message="Response ready.",
            equipment="llm",
            category="planning",
            payload={},
        ))

    return session


# ── Live event consumption ────────────────────────────────────────────────────

def _consume_one_live_event(session: SessionModel):
    """Pop one event and update session UI state. Call under lock."""
    if not session.live_event_queue:
        return

    event = session.live_event_queue.pop(0)
    session.current_activity     = event.message
    session.background_job_label = event.message
    session.activity_log.append(f"[{event.category.upper()}] {event.message}")
    session.activity_log = session.activity_log[-20:]

    # Update equipment status for digital twin animation
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

    Invariants:
    - Never calls LLM (avoids 500 errors / timeouts in background thread)
    - Each step wrapped in try/except (one bad step never kills the job)
    - Always sets background_job_active=False on exit (success OR failure)
    - Lock held only for state mutations, not for slow I/O
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    def _mark_done(success: bool, error_msg: str = ""):
        with lock:
            session.background_job_active  = False
            session.background_job_status  = "completed" if success else "failed"
            session.background_job_label   = None
            session.current_activity       = None
            session.equipment_status       = EquipmentStatusModel()

            if not success:
                session.background_job_error = error_msg
                session.agent_state.messages.append({
                    "role":    "assistant",
                    "content": (
                        f"⚠️ The workflow stopped due to an error.\n\n"
                        f"**Details:** `{error_msg}`\n\n"
                        f"Any results collected before the error have been saved."
                    ),
                })
            else:
                results  = session.agent_state.results_store
                n_evals  = sum(len(r.get("X", [])) for r in results)
                n_fails  = sum(r.get("failed_samples", 0) for r in results)
                best_e   = max(
                    (r.get("best_energy") or 0.0 for r in results),
                    default=0.0,
                )
                obj      = (
                    session.extracted_campaign.objective_metric
                    if session.extracted_campaign else "objective"
                )
                powers_done = [
                    f"{int(r['power_W'])}" for r in results if r.get("X")
                ]

                session.agent_state.messages.append({
                    "role":    "assistant",
                    "content": (
                        f"✅ **Workflow complete.**\n\n"
                        f"| Metric | Value |\n"
                        f"|--------|-------|\n"
                        f"| Experiments run | {n_evals} |\n"
                        f"| Best {obj} | {best_e:.2f} |\n"
                        f"| Failed steps | {n_fails} |\n"
                        f"| Conditions completed | {', '.join(powers_done) or 'none'} |\n\n"
                        f"Ask me to **generate a summary figure**, "
                        f"**analyse the results**, or **continue tomorrow**."
                    ),
                })

    try:
        while True:
            with lock:
                has_events = bool(session.live_event_queue)
                has_steps  = (
                    session.background_job_index < len(session.background_job_plan)
                )

            if has_events:
                with lock:
                    _consume_one_live_event(session)

            elif has_steps:
                with lock:
                    step = session.background_job_plan[session.background_job_index]
                    session.background_job_label  = step.get("kind", "running")
                    session.background_job_status = "running"

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
                        session.background_job_index += 1  # skip, continue

            else:
                _mark_done(success=True)
                break

            time.sleep(0.25)

    except Exception as fatal:
        _mark_done(
            success=False,
            error_msg=f"{type(fatal).__name__}: {fatal}",
        )


# ── Workflow confirmation ─────────────────────────────────────────────────────

def confirm_pending(session_id: str, proceed: bool) -> SessionModel:
    """
    Called from API request thread when user approves or aborts a workflow.

    Special handling for extract_and_check_feasibility:
    - Runs synchronously here (not in background job)
    - Does NOT require user approval — it's a read-only operation
    - Only run_extracted_campaign requires approval + background job
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        if not session.agent_state.awaiting_confirmation:
            return session

    if proceed:
        pending_calls = session.agent_state.pending_tool_calls

        # Check if this is purely a feasibility check (no execution)
        tool_names = [tc["function"]["name"] for tc in pending_calls]
        is_feasibility_only = (
            all(n == "extract_and_check_feasibility" for n in tool_names)
        )

        if is_feasibility_only:
            # Run feasibility synchronously — no background job needed
            with lock:
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []
                session.equipment_status = EquipmentStatusModel(knowledge=True)
                session.current_activity = "Checking feasibility..."

            for tc in pending_calls:
                args = {}
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    pass
                case_name = args.get("case_name", "Case Study")

                # Inject tool response BEFORE executing so message history
                # is valid for subsequent LLM calls
                # OpenAI requires: assistant tool_calls → tool response
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         tc["function"]["name"],
                    "content":      json.dumps({
                        "status":    "running",
                        "case_name": case_name,
                    }),
                })

                step = {"kind": "extract_feasibility", "case_name": case_name}
                try:
                    execute_plan_step(session, step, query_database)
                except Exception as e:
                    session.agent_state.messages.append({
                        "role":    "assistant",
                        "content": f"Error during feasibility check: `{e}`",
                    })

            with lock:
                session.equipment_status = EquipmentStatusModel()
                session.current_activity = None

        else:
            # Build plan for background execution
            # extract_and_check_feasibility is excluded from plan
            # (handled above or already done)
            with lock:
                plan = build_execution_plan_from_tool_calls(
                    session, pending_calls
                )

                # If plan is empty after filtering, don't start a job
                if not plan:
                    session.agent_state.awaiting_confirmation = False
                    session.agent_state.pending_tool_calls    = []
                    return session

                session.background_job_plan        = plan
                session.background_job_index       = 0
                session.background_job_status      = "running"
                session.background_job_active      = True
                session.background_job_label       = "Initialising..."
                session.background_job_error       = None
                session.live_event_queue           = []
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []

            threading.Thread(
                target=_run_background_job,
                args=(session_id,),
                daemon=True,
                name=f"maestro-job-{session_id[:8]}",
            ).start()

    else:
        # Abort path
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

        llm_plan(session)

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
    """Serialise full session state for the frontend."""
    results = session.agent_state.results_store

    # Dynamic metric labels — derived from campaign objective
    obj_label = "Objective"
    cond_label = "Conditions"
    if session.extracted_campaign:
        obj_label  = session.extracted_campaign.objective_metric or "Objective"
        conds      = session.extracted_campaign.operating_conditions
        if conds:
            cond_label = conds[0].get("name", "Conditions")

    return {
        "session_id":                 session.session_id,
        "messages":                   session.agent_state.messages,
        "results_store":              results,
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
        # Dynamic metric labels for frontend
        "metric_labels": {
            "experiments":  "Experiments",
            "best_result":  f"Best {obj_label}",
            "conditions":   f"{cond_label} Run",
            "failures":     "Failed Steps",
        },
        # Phase 2C: resource log for Gantt
        "resource_log":               session.resource_log[-100:],
    }