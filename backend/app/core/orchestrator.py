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

    # Auto-handle plan_workflow — store plan on session, show in editor
    if session.agent_state.awaiting_confirmation:
        pending_names = [
            tc["function"]["name"]
            for tc in session.agent_state.pending_tool_calls
        ]
        has_plan_workflow = any(n == "plan_workflow" for n in pending_names)

        if has_plan_workflow:
            for tc in session.agent_state.pending_tool_calls:
                if tc["function"]["name"] == "plan_workflow":
                    args = {}
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except Exception:
                        pass

                    from app.core.models import WorkflowPlan, WorkflowStep
                    steps = []
                    for s in args.get("steps", []):
                        # Set editable_fields based on step kind
                        editable = []
                        if s.get("kind") == "optimise_condition":
                            editable = ["n_calls", "n_initial_points", "condition_value"]
                            for fp in s.get("free_params", []):
                                editable += [f"{fp['name']}_min", f"{fp['name']}_max"]
                        elif s.get("kind") in ("prepare_sample", "test_sample"):
                            editable = list(s.get("params", {}).keys()) + list(s.get("conditions", {}).keys())
                        s["editable_fields"] = editable
                        steps.append(WorkflowStep(**s))

                    session.pending_plan = WorkflowPlan(
                        summary=args.get("summary", "Proposed workflow"),
                        steps=steps,
                        source="agent",
                    )
                    # Keep awaiting_confirmation=True so frontend shows editor
                    break

    # Handle prepare_sample / test_sample / list_samples directly
    # (no approval needed for single instrument actions)
    if session.agent_state.awaiting_confirmation:
        pending_names = [
            tc["function"]["name"]
            for tc in session.agent_state.pending_tool_calls
        ]
        single_instrument_actions = {"prepare_sample", "test_sample", "list_samples"}
        all_single = all(n in single_instrument_actions for n in pending_names)

        if all_single:
            pending_calls = list(session.agent_state.pending_tool_calls)
            with lock:
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []

            dag_context = {}
            for tc in pending_calls:
                args = {}
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    pass

                name = tc["function"]["name"]
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         name,
                    "content":      json.dumps({"status": "running"}),
                })

                if name == "prepare_sample":
                    step = {
                        "kind":       "prepare_sample",
                        "params":     args.get("params", {}),
                        "instrument": "SamplerAgent",
                        "produces":   "sample_id",
                    }
                    try:
                        execute_plan_step(session, step, query_database, dag_context)
                    except Exception as e:
                        session.agent_state.messages.append({
                            "role": "assistant",
                            "content": f"Error preparing sample: `{e}`",
                        })

                elif name == "test_sample":
                    step = {
                        "kind":       "test_sample",
                        "sample_ref": args.get("sample_id", ""),
                        "conditions": args.get("conditions", {}),
                        "measures":   args.get("measures", "specific_energy"),
                        "instrument": "TesterAgent",
                    }
                    try:
                        execute_plan_step(session, step, query_database, dag_context)
                    except Exception as e:
                        session.agent_state.messages.append({
                            "role": "assistant",
                            "content": f"Error testing sample: `{e}`",
                        })

                elif name == "list_samples":
                    try:
                        execute_plan_step(session, {"kind": "list_samples"}, query_database, dag_context)
                    except Exception as e:
                        session.agent_state.messages.append({
                            "role": "assistant",
                            "content": f"Error listing samples: `{e}`",
                        })            

    # Auto-handle resume_outstanding_tasks
    if session.agent_state.awaiting_confirmation:
        pending_names = [
            tc["function"]["name"]
            for tc in session.agent_state.pending_tool_calls
        ]
        if any(n == "resume_outstanding_tasks" for n in pending_names):
            pending_calls = list(session.agent_state.pending_tool_calls)
            with lock:
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []

            for tc in pending_calls:
                if tc["function"]["name"] == "resume_outstanding_tasks":
                    session.agent_state.messages.append({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "name":         tc["function"]["name"],
                        "content":      json.dumps({"status": "running"}),
                    })
                    resume_outstanding_tasks(session_id)
                    break

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
    if session.extracted_campaign:
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            session.active_condition_key = ocs[0].get("name", "power_W")

def execute_plan(session_id: str, plan_dict: dict) -> SessionModel:
    """
    Execute a WorkflowPlan that was approved (and optionally edited)
    by the user in the WorkflowPlanEditor.

    Called from POST /execute-plan.
    Converts the plan dict into background job steps and starts execution.
    """
    from app.core.models import WorkflowPlan
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    plan  = WorkflowPlan(**plan_dict)
    steps = [step.model_dump() for step in plan.steps]

    with lock:
        session.background_job_plan        = steps
        session.background_job_index       = 0
        session.background_job_status      = "running"
        session.background_job_active      = True
        session.background_job_label       = "Initialising..."
        session.background_job_error       = None
        session.live_event_queue           = []
        session.pending_plan               = None
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []

        # Inject tool response for plan_workflow tool call
        _inject_missing_tool_responses(session)

    threading.Thread(
        target=_run_background_job,
        args=(session_id,),
        daemon=True,
        name=f"maestro-plan-{session_id[:8]}",
    ).start()

    return session

def resume_outstanding_tasks(session_id: str) -> SessionModel:
    """
    Advance to next day and re-queue all outstanding tasks for execution.
    Called when user says 'continue tomorrow' or similar.
    """
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    # Advance virtual clock
    advance_to_next_day(session)

    outstanding = list(session.outstanding_tasks)
    if not outstanding:
        session.agent_state.messages.append({
            "role":    "assistant",
            "content": (
                f"Advanced to Day {session.virtual_day_index}. "
                f"No outstanding tasks to resume."
            ),
        })
        return session

    # Build plan from outstanding tasks
    plan = []
    for task in outstanding:
        kind = task.get("kind", "optimise_condition")
        if kind in ("optimise_condition", "optimise_power"):
            plan.append({
                "kind":             "optimise_condition",
                "condition_label":  task.get("condition_label", "power_W"),
                "condition_value":  float(task.get("condition_value", task.get("power_W", 0))),
                "condition_unit":   task.get("condition_unit", ""),
                "free_params":      task.get("free_params", [
                    {"name": "active_material", "min": 88.0, "max": 98.0, "unit": "wt%"},
                    {"name": "porosity",        "min": 20.0, "max": 60.0, "unit": "%"},
                ]),
                "objective_metric": task.get("objective_metric", "specific_energy"),
                "n_calls":          int(task.get("remaining_n_calls", 20)),
                "n_initial_points": 3,   # fewer init points for resumption
            })

    if not plan:
        return session

    with lock:
        # Clear outstanding tasks — they're now in the plan
        session.outstanding_tasks          = []
        session.background_job_plan        = plan
        session.background_job_index       = 0
        session.background_job_status      = "running"
        session.background_job_active      = True
        session.background_job_label       = "Resuming incomplete runs..."
        session.background_job_error       = None
        session.live_event_queue           = []
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []

    session.agent_state.messages.append({
        "role":    "assistant",
        "content": (
            f"▶️ **Resuming on Day {session.virtual_day_index}.**\n\n"
            f"Queued {len(plan)} incomplete run(s) for execution. "
            f"The workflow is now running."
        ),
    })

    threading.Thread(
        target=_run_background_job,
        args=(session_id,),
        daemon=True,
        name=f"maestro-resume-{session_id[:8]}",
    ).start()

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
    """Repair orphaned tool_call_ids in message history."""
    messages = session.agent_state.messages
    responded_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                responded_ids.add(tc_id)

    injections = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            tc_id   = tc.get("id")
            tc_name = tc.get("function", {}).get("name", "unknown_tool")
            if tc_id and tc_id not in responded_ids:
                injections.append((i + 1, {
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "name":         tc_name,
                    "content":      json.dumps({
                        "status":  "completed",
                        "message": f"Tool '{tc_name}' executed successfully.",
                    }),
                }))
                responded_ids.add(tc_id)

    for insert_idx, tool_msg in reversed(injections):
        messages.insert(insert_idx, tool_msg)

def _run_background_job(session_id: str):
    """
    Worker thread: executes the approved plan step by step.

    Invariants:
    - Never calls LLM
    - Each step wrapped in try/except
    - Always sets background_job_active=False on exit
    - Lock held only for state mutations
    - dag_context shared across all steps for DAG variable resolution
    """
    session     = get_session(session_id)
    lock        = _lock_for(session_id)
    dag_context: dict = {}   # shared across all steps in this job

    def mark_done(success: bool, error_msg: str = ""):
        """Inner helper — closes over session and lock."""
        with lock:
            session.background_job_active  = False
            session.background_job_status  = "completed" if success else "failed"
            session.background_job_label   = None
            session.current_activity       = None
            session.equipment_status       = EquipmentStatusModel()
            session.pending_plan           = None

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
                obj_label  = (
                    session.extracted_campaign.objective_metric
                    if session.extracted_campaign else "objective"
                )
                cond_label = session.active_condition_key or "condition"

                conds_done = [
                    f"{r.get('condition_label', cond_label)}"
                    f"={r.get('condition_value', r.get('power_W', '?'))}"
                    for r in results if r.get("X")
                ]

                outstanding      = session.outstanding_tasks
                outstanding_note = ""
                if outstanding:
                    outstanding_note = (
                        f"\n\n⏳ **{len(outstanding)} incomplete run(s)** — "
                        f"lab time ran out."
                    )

                is_plotter_job = any(
                    step.get("kind") == "plotter"
                    for step in session.background_job_plan
                )

                if is_plotter_job and session.show_plotter_image:
                    session.agent_state.messages.append({
                        "role":    "assistant",
                        "content": (
                            f"Here is the optimisation summary figure:\n\n"
                            f"![Optimisation Summary]"
                            f"(/api/plot/{session.session_id})\n\n"
                            f"The figure shows the parameter space explored at each "
                            f"operating condition, with the optimal parameter path in "
                            f"the final panel. Ask me to analyse the results or "
                            f"continue tomorrow."
                        ),
                    })
                elif n_evals > 0:
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
                            f"{', '.join(conds_done) or 'none'} |"
                            f"{outstanding_note}\n\n"
                            f"Ask me to **generate a summary figure**, "
                            f"**analyse the results**, or **continue tomorrow**."
                        ),
                    })

            # Final event to unblock frontend spinner
            session.live_event_queue.append(ExecutionEvent(
                event_type="job_complete",
                message="Job finished.",
                equipment=None,
                category="system",
                payload={
                    "background_job_active": False,
                    "background_job_status": session.background_job_status,
                },
            ))

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
                    # Use step label if available, else kind
                    session.background_job_label  = (
                        step.get("label") or step.get("kind", "running")
                    )
                    session.background_job_status = "running"

                try:
                    # Pass dag_context so steps can share outputs
                    result = execute_plan_step(
                        session, step, query_database, dag_context
                    )
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
                        session.background_job_index += 1  # skip, continue

            else:
                mark_done(success=True)
                break

            time.sleep(0.25)

    except Exception as fatal:
        mark_done(
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
    results    = session.agent_state.results_store
    obj_label  = "Objective"
    cond_label = session.active_condition_key or "Condition"

    if session.extracted_campaign:
        obj_label  = session.extracted_campaign.objective_metric or "Objective"
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
        # Phase 3: sample registry
        "sample_registry":            [s.model_dump() for s in session.sample_registry],
        # Phase 3: pending workflow plan
        "pending_plan":               (
            session.pending_plan.model_dump()
            if session.pending_plan else None
        ),
        "metric_labels": {
            "experiments": "Experiments",
            "best_result": f"Best {obj_label}",
            "conditions":  f"{cond_label} Runs",
            "failures":    "Failed Steps",
        },
        "resource_log": session.resource_log[-100:],
    }