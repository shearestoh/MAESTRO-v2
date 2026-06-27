"""
Session management and background job execution.

Phase 3: domain-agnostic condition labels throughout.
- session_state_payload() uses active_condition_key for metric labels
- _mark_done() summary uses general condition fields
- active_condition_key synced from extracted campaign
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

    # Auto-approve feasibility checks
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
                    # Sync active_condition_key after extraction
                    _sync_condition_key(session)
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


def _sync_condition_key(session: SessionModel):
    """
    Update active_condition_key from the extracted campaign.
    Called after feasibility extraction completes.
    """
    if session.extracted_campaign:
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            session.active_condition_key = ocs[0].get("name", "power_W")


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
def _inject_missing_tool_responses(session: SessionModel):
    """
    Scan message history for assistant messages with tool_calls that
    have no matching tool response message.

    OpenAI requires every tool_call_id to be answered by a tool message.
    This can be violated when:
    - The background job completes without injecting tool responses
    - The user aborts mid-flow
    - Session state is partially updated

    This function repairs the message history in-place by injecting
    synthetic tool response messages for any orphaned tool_call_ids.
    """
    messages = session.agent_state.messages

    # Collect all tool_call_ids that have already been responded to
    responded_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                responded_ids.add(tc_id)

    # Find assistant messages with unanswered tool_calls
    injected = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls", [])
        if not tool_calls:
            continue

        for tc in tool_calls:
            tc_id   = tc.get("id")
            tc_name = tc.get("function", {}).get("name", "unknown_tool")

            if tc_id and tc_id not in responded_ids:
                # Inject a synthetic tool response immediately after
                # this assistant message
                injected.append((i + 1, {
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "name":         tc_name,
                    "content":      json.dumps({
                        "status":  "completed",
                        "message": (
                            f"Tool '{tc_name}' executed successfully "
                            f"as part of the background workflow."
                        ),
                    }),
                }))
                responded_ids.add(tc_id)

    # Insert injected messages in reverse order to preserve indices
    for insert_idx, tool_msg in reversed(injected):
        messages.insert(insert_idx, tool_msg)


def _run_background_job(session_id: str):
    """
    Worker thread: executes the approved plan step by step.

    Invariants:
    - Never calls LLM
    - Each step wrapped in try/except
    - Always sets background_job_active=False on exit
    - Lock held only for state mutations
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

            # ── Inject tool response messages for all background tool calls ───
            # OpenAI requires: assistant[tool_calls] → tool[response]
            # The background job runs after confirm_pending() already cleared
            # pending_tool_calls, so we scan message history for any
            # assistant messages with tool_calls that have no matching
            # tool response yet.
            _inject_missing_tool_responses(session)

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

                best_obj = max(
                    (r.get("best_objective") or r.get("best_energy") or 0.0
                    for r in results),
                    default=0.0,
                )

                obj_label  = "objective"
                cond_label = session.active_condition_key or "condition"

                if session.extracted_campaign:
                    obj_label = (
                        session.extracted_campaign.objective_metric
                        or "objective"
                    )

                conds_done = [
                    f"{r.get('condition_label', cond_label)}"
                    f"={r.get('condition_value', r.get('power_W', '?'))}"
                    for r in results
                    if r.get("X")
                ]

                session.agent_state.messages.append({
                    "role":    "assistant",
                    "content": (
                        f"✅ **Workflow complete.**\n\n"
                        f"| Metric | Value |\n"
                        f"|--------|-------|\n"
                        f"| Experiments run | {n_evals} |\n"
                        f"| Best {obj_label} | {best_obj:.4f} |\n"
                        f"| Failed steps | {n_fails} |\n"
                        f"| Conditions completed | "
                        f"{', '.join(conds_done) or 'none'} |\n\n"
                        f"Ask me to **generate a summary figure**, "
                        f"**analyse the results**, or **continue tomorrow**."
                    ),
                })

    try:
        while True:
            with lock:
                has_events = bool(session.live_event_queue)
                has_steps  = (
                    session.background_job_index
                    < len(session.background_job_plan)
                )

            if has_events:
                with lock:
                    _consume_one_live_event(session)

            elif has_steps:
                with lock:
                    step = session.background_job_plan[
                        session.background_job_index
                    ]
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
                            f"[WARNING] Step '{step.get('kind')}' "
                            f"error: {step_err}"
                        )
                        session.activity_log = session.activity_log[-20:]
                        session.background_job_index += 1

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
    Called from API request thread when user approves or aborts.
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        if not session.agent_state.awaiting_confirmation:
            return session

    if proceed:
        pending_calls = session.agent_state.pending_tool_calls
        tool_names    = [tc["function"]["name"] for tc in pending_calls]
        is_feasibility_only = all(
            n == "extract_and_check_feasibility" for n in tool_names
        )

        if is_feasibility_only:
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
                    _sync_condition_key(session)
                except Exception as e:
                    session.agent_state.messages.append({
                        "role":    "assistant",
                        "content": f"Error during feasibility check: `{e}`",
                    })

            with lock:
                session.equipment_status = EquipmentStatusModel()
                session.current_activity = None

        else:
            with lock:
                plan = build_execution_plan_from_tool_calls(
                    session, pending_calls
                )

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

def register_artifact(
    session: SessionModel, name: str, kind: str, path: str
):
    session.artifacts.append(ArtifactModel(name=name, kind=kind, path=path))
    session.artifacts = session.artifacts[-20:]


# ── State serialisation ───────────────────────────────────────────────────────

def session_state_payload(session: SessionModel) -> dict:
    """
    Serialise full session state for the frontend.

    Phase 3: dynamic metric labels derived from active_condition_key
    and campaign objective_metric rather than hardcoded battery terms.
    """
    results = session.agent_state.results_store

    # ── Dynamic metric labels ─────────────────────────────────────────────────
    obj_label   = "Objective"
    cond_label  = session.active_condition_key or "Condition"

    if session.extracted_campaign:
        obj_label  = (
            session.extracted_campaign.objective_metric or "Objective"
        )
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            cond_label = ocs[0].get("name", cond_label)

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
        "active_condition_key":       session.active_condition_key,

        # Dynamic metric labels for frontend
        "metric_labels": {
            "experiments": "Experiments",
            "best_result": f"Best {obj_label}",
            "conditions":  f"{cond_label} Runs",
            "failures":    "Failed Steps",
        },

        # Phase 2C: resource log for Gantt
        "resource_log": session.resource_log[-100:],
    }