from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Dict

from app.core.database import ensure_db, query_database, reset_evaluations
from app.core.llm import llm_plan, _NON_INSTRUMENT_ACTIONS
from app.core.models import (
    AgentStateModel,
    ArtifactModel,
    EquipmentStatusModel,
    ExecutionEvent,
    SessionModel,
    WorkflowPlan,
    WorkflowStep,
)
from app.core.tools import (
    build_dynamic_timeline,
    build_execution_plan_from_tool_calls,
    execute_plan_step,
    compute_projected_schedule,
)

SESSIONS:      Dict[str, SessionModel]   = {}
SESSION_LOCKS: Dict[str, threading.Lock] = {}

_INSTRUMENT_STEP_KINDS     = {"synthesise", "characterise", "optimise_condition", "extract_feasibility"}
_NON_INSTRUMENT_STEP_KINDS = {"list_samples", "generate_plot", "analyse_data", "query_database"}


def _lock_for(session_id: str) -> threading.Lock:
    if session_id not in SESSION_LOCKS:
        SESSION_LOCKS[session_id] = threading.Lock()
    return SESSION_LOCKS[session_id]


def _welcome_message() -> dict:
    from app.core.lab_config import get_lab_settings
    lab_name = get_lab_settings().lab_name or "your lab"
    return {
        "role": "assistant",
        "content": (
            f"Welcome to **MAESTRO** — your agentic orchestrator for **{lab_name}**.\n\n"
            "You can:\n"
            "- Design and run experimental campaigns\n"
            "- Upload papers and manuals to the Library\n"
            "- Query and analyse your experimental results\n"
            "- Configure your lab via Lab Setup\n\n"
            "What would you like to explore today?"
        ),
    }


def create_session() -> SessionModel:
    ensure_db()
    session_id  = str(uuid.uuid4())
    session     = SessionModel(
        session_id=session_id,
        agent_state=AgentStateModel(messages=[_welcome_message()]),
        current_mission="Awaiting instruction.",
    )
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> SessionModel:
    if session_id not in SESSIONS:
        raise KeyError(f"Unknown session_id: {session_id}")
    return SESSIONS[session_id]


def reset_session(session_id: str) -> SessionModel:
    reset_evaluations()
    SESSIONS.pop(session_id, None)
    SESSION_LOCKS.pop(session_id, None)
    return create_session()


def _plan_requires_approval(plan: list) -> bool:
    return any(step.get("kind") in _INSTRUMENT_STEP_KINDS for step in plan)


def _append_tool_response(session: SessionModel, tool_call_id: str, name: str, content: str) -> None:
    for msg in reversed(session.agent_state.messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if tool_call_id in {tc.get("id") for tc in msg["tool_calls"]}:
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call_id,
                    "name":         name,
                    "content":      content,
                })
                return
        if msg.get("role") == "user":
            break
    print(f"[WARN] Orphaned tool response: tool_call_id={tool_call_id}, name={name}")


def post_user_message(session_id: str, text: str) -> SessionModel:
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    with lock:
        if session.pending_plan is not None:
            session.pending_plan = None
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []

        session.agent_state.messages.append({"role": "user", "content": text})
        session.current_mission  = text
        session.equipment_status = EquipmentStatusModel(llm=True)
        session.current_activity = "Thinking..."
        session.live_event_queue.append(ExecutionEvent(
            event_type="llm_thinking",
            message="Thinking...",
            equipment="llm",
            category="planning",
            payload={},
        ))

    llm_plan(session)

    if session.agent_state.awaiting_confirmation:
        pending_calls = list(session.agent_state.pending_tool_calls)
        pending_names = [tc["function"]["name"] for tc in pending_calls]
        plan          = build_execution_plan_from_tool_calls(session, pending_calls)

        if _plan_requires_approval(plan):
            _handle_plan_requiring_approval(session, lock, plan, pending_calls, pending_names)
        else:
            _execute_non_instrument_actions(session, lock, plan, pending_calls)

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


def _check_plan_feasibility(session: SessionModel, steps: list) -> str | None:
    from app.core.tool_registry import TOOL_REGISTRY

    instrument_steps = [
        s for s in steps
        if s.get("kind") in ("synthesise", "characterise", "optimise_condition")
    ]
    if not instrument_steps:
        return None

    required_params:  set[str] = set()
    required_outputs: set[str] = set()

    for step in instrument_steps:
        kind = step.get("kind")
        if kind == "synthesise":
            required_params.update(k for k in (step.get("params") or {}) if k)
        elif kind == "characterise":
            if step.get("measures"):
                required_outputs.add(step["measures"])
            required_params.update(k for k in (step.get("conditions") or {}) if k)
        elif kind == "optimise_condition":
            required_params.update(
                fp.get("name", "") for fp in (step.get("free_params") or []) if fp.get("name")
            )
            if step.get("objective_metric"):
                required_outputs.add(step["objective_metric"])

    if not required_params and not required_outputs:
        return None

    feasibility = TOOL_REGISTRY.check_feasibility(list(required_params), list(required_outputs))
    if feasibility["feasible"]:
        return None

    missing_p = feasibility.get("missing_params", [])
    missing_o = feasibility.get("missing_outputs", [])
    parts     = []
    if missing_p:
        parts.append(f"parameters not controllable: **{', '.join(missing_p)}**")
    if missing_o:
        parts.append(f"objectives not measurable: **{', '.join(missing_o)}**")

    return (
        f"⚠️ **Capability check failed.** This workflow requires {' and '.join(parts)}.\n\n"
        f"Available parameters: {feasibility.get('available_params') or 'none'}\n"
        f"Available outputs: {feasibility.get('available_outputs') or 'none'}\n\n"
        f"Please register the appropriate instruments in Lab Setup, or adjust the workflow."
    )


def _handle_plan_requiring_approval(session, lock, plan, pending_calls, pending_names):
    has_feasibility   = any(n == "extract_and_check_feasibility" for n in pending_names)
    has_plan_workflow = any(n == "plan_workflow" for n in pending_names)

    if has_feasibility:
        with lock:
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []
            session.equipment_status = EquipmentStatusModel(knowledge=True)
            session.current_activity = "Checking feasibility..."

        for tc in pending_calls:
            if tc["function"]["name"] != "extract_and_check_feasibility":
                continue
            args      = _safe_parse_args(tc)
            case_name = args.get("case_name", "Case Study")
            _append_tool_response(
                session, tc["id"], tc["function"]["name"],
                json.dumps({"status": "running", "case_name": case_name}),
            )
            try:
                execute_plan_step(
                    session,
                    {"kind": "extract_feasibility", "case_name": case_name},
                    query_database,
                )
                _sync_condition_key(session)
                _auto_build_campaign_plan(session)
            except Exception as e:
                session.agent_state.messages.append({
                    "role": "assistant",
                    "content": f"Error during feasibility check: `{e}`",
                })

        with lock:
            session.equipment_status = EquipmentStatusModel()
            session.current_activity = None
        return

    if has_plan_workflow:
        all_steps: list[WorkflowStep] = []
        summaries: list[str]          = []

        for tc in pending_calls:
            if tc["function"]["name"] != "plan_workflow":
                continue
            args = _safe_parse_args(tc)
            summaries.append(args.get("summary", ""))
            for s in args.get("steps", []):
                s = _normalise_step(s, session)
                try:
                    all_steps.append(WorkflowStep(**s))
                except Exception as e:
                    print(f"[WARN] Could not parse workflow step: {e} | step: {s}")

        if not all_steps:
            session.agent_state.messages.append({
                "role": "assistant",
                "content": "I couldn't build a valid workflow plan. Please try describing the steps again.",
            })
            for tc in pending_calls:
                if tc["function"]["name"] == "plan_workflow":
                    _append_tool_response(
                        session, tc["id"], "plan_workflow",
                        json.dumps({"status": "error", "message": "No valid steps parsed."}),
                    )
            return

        feasibility_warning = _check_plan_feasibility(
            session, [s.model_dump() for s in all_steps]
        )
        if feasibility_warning:
            session.agent_state.messages.append({
                "role": "assistant", "content": feasibility_warning,
            })
            for tc in pending_calls:
                if tc["function"]["name"] == "plan_workflow":
                    _append_tool_response(
                        session, tc["id"], "plan_workflow",
                        json.dumps({"status": "rejected", "message": "Capability check failed."}),
                    )
            return

        combined_summary = (
            summaries[0] if len(summaries) == 1
            else f"{len(all_steps)}-step workflow: " + "; ".join(s for s in summaries if s)
        )
        session.pending_plan = WorkflowPlan(
            summary=combined_summary,
            steps=all_steps,
            source="agent",
        )
        session.projected_schedule = compute_projected_schedule(
            plan=[s.model_dump() for s in all_steps]
        )

        for tc in pending_calls:
            if tc["function"]["name"] == "plan_workflow":
                _append_tool_response(
                    session, tc["id"], "plan_workflow",
                    json.dumps({"status": "pending_approval", "message": "Workflow presented for approval."}),
                )


def _execute_non_instrument_actions(session, lock, plan, pending_calls):
    with lock:
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []

    dag_context  = {}
    tool_results = []

    for step in plan:
        kind = step.get("kind", "")
        if kind not in _NON_INSTRUMENT_STEP_KINDS:
            continue
        try:
            result = execute_plan_step(session, step, query_database, dag_context)
        except Exception as e:
            result = {"status": "error", "message": str(e)}
        tool_results.append((kind, result))

        if kind == "generate_plot" and result.get("status") == "ok":
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": f"Here is the summary figure:\n\n![Summary](/api/plot/{session.session_id})",
            })

    summary_result = json.dumps(
        {"status": "ok", "results": [r for _, r in tool_results]}, default=str
    )
    for tc in pending_calls:
        _append_tool_response(session, tc["id"], tc["function"]["name"], summary_result)

    needs_followup = any(kind in ("query_database", "list_samples") for kind, _ in tool_results)
    if needs_followup:
        with lock:
            session.equipment_status.llm = True
            session.current_activity     = "Interpreting results..."
        llm_plan(session)
        with lock:
            session.equipment_status.llm = False
            session.current_activity     = None

        if session.agent_state.awaiting_confirmation:
            followup_calls = list(session.agent_state.pending_tool_calls)
            followup_plan  = build_execution_plan_from_tool_calls(session, followup_calls)
            if not _plan_requires_approval(followup_plan):
                _execute_non_instrument_actions(session, lock, followup_plan, followup_calls)


def _sync_condition_key(session: SessionModel) -> None:
    if session.extracted_campaign:
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            session.active_condition_key = ocs[0].get("name", "condition")


def _auto_build_campaign_plan(session: SessionModel) -> None:
    if not session.extracted_campaign:
        return
    c            = session.extracted_campaign
    param_lookup = {p["name"].lower(): p for p in c.parameter_space}
    free_params  = _resolve_free_params(param_lookup)
    steps        = []

    if not c.operating_conditions:
        steps.append(WorkflowStep(
            step_id=str(uuid.uuid4())[:8],
            kind="optimise_condition",
            label="BO Campaign",
            condition_label="run",
            condition_value=1.0,
            condition_unit="",
            free_params=free_params,
            objective_metric=c.objective_metric or "objective",
            optimiser_name=session.optimiser_config.name,
            n_calls=session.optimiser_config.n_calls,
            n_initial_points=session.optimiser_config.n_initial_points,
            instrument_id="optimiser",
            status="pending",
        ))
    else:
        primary_oc = c.operating_conditions[0]
        session.active_condition_key = primary_oc.get("name", "condition")
        for oc in c.operating_conditions:
            oc_name, oc_unit = oc.get("name", "condition"), oc.get("unit", "")
            for value in oc.get("values", []):
                steps.append(WorkflowStep(
                    step_id=str(uuid.uuid4())[:8],
                    kind="optimise_condition",
                    label=f"BO @ {oc_name}={value} {oc_unit}".strip(),
                    condition_label=oc_name,
                    condition_value=float(value),
                    condition_unit=oc_unit,
                    free_params=free_params,
                    objective_metric=c.objective_metric or "objective",
                    optimiser_name=session.optimiser_config.name,
                    n_calls=session.optimiser_config.n_calls,
                    n_initial_points=session.optimiser_config.n_initial_points,
                    instrument_id="optimiser",
                    status="pending",
                ))

    if steps:
        session.pending_plan = WorkflowPlan(
            summary=f"Reproduce: {c.target_case_study}",
            steps=steps,
            source="paper",
        )


def _resolve_free_params(param_lookup: Dict[str, dict]) -> list:
    return [
        {
            "name": p.get("name", name),
            "min":  float(p["min"]),
            "max":  float(p["max"]),
            "unit": p.get("unit", ""),
        }
        for name, p in param_lookup.items()
        if p.get("min") is not None and p.get("max") is not None
    ]


def _safe_parse_args(tc: dict) -> dict:
    try:
        return json.loads(tc["function"].get("arguments") or "{}")
    except (json.JSONDecodeError, KeyError):
        return {}


def _normalise_step(s: dict, session: SessionModel) -> dict:
    kind = s.get("kind", "step")

    if not s.get("label"):
        cond = s.get("condition_label", "")
        val  = s.get("condition_value", "")
        opt  = s.get("optimiser_name", "")
        if kind == "optimise_condition" and cond:
            s["label"] = f"Optimise {cond}={val}" + (f" [{opt}]" if opt else "")
        elif kind == "synthesise":
            s["label"] = "Synthesise sample"
        elif kind == "characterise":
            s["label"] = "Characterise sample"
        else:
            s["label"] = kind.replace("_", " ").title()

    s.setdefault("step_id", str(uuid.uuid4())[:8])
    s.setdefault("status", "pending")
    s.setdefault("dependencies", [])
    s["instrument_id"] = str(s.get("instrument_id") or s.get("instrument") or kind or "unknown")

    if kind == "optimise_condition":
        s.setdefault("condition_label", "condition")
        s["condition_value"] = float(s.get("condition_value") or 0.0)
        s.setdefault("free_params", [])
        s.setdefault("objective_metric", "objective")
        s.setdefault("n_calls", session.optimiser_config.n_calls)
        s.setdefault("n_initial_points", session.optimiser_config.n_initial_points)
        s.setdefault("optimiser_name", session.optimiser_config.name)

    editable = []
    if kind == "optimise_condition":
        editable = ["n_calls", "n_initial_points", "condition_value"]
        for fp in s.get("free_params", []):
            editable += [f"{fp['name']}_min", f"{fp['name']}_max"]
    elif kind in ("synthesise", "characterise"):
        editable = list(s.get("params", {}).keys()) + list(s.get("conditions", {}).keys())
    s["editable_fields"] = editable

    return s


def execute_plan(session_id: str, plan_dict: dict) -> SessionModel:
    session = get_session(session_id)
    lock    = _lock_for(session_id)
    plan    = WorkflowPlan(**plan_dict)
    steps   = [step.model_dump() for step in plan.steps]

    with lock:
        session.background_job_plan        = steps
        session.background_job_index       = 0
        session.background_job_status      = "running"
        session.background_job_active      = True
        session.background_job_label       = "Initialising..."
        session.background_job_error       = None
        session.live_event_queue           = []
        session.pending_plan               = None
        session.projected_schedule         = compute_projected_schedule(plan=steps)
        session.bo_iteration_counts        = {}
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []

    threading.Thread(
        target=_run_background_job,
        args=(session_id,),
        daemon=True,
        name=f"maestro-plan-{session_id[:8]}",
    ).start()

    return session


def confirm_pending(session_id: str, proceed: bool) -> SessionModel:
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    has_pending = session.agent_state.awaiting_confirmation or session.pending_plan is not None
    if not has_pending:
        return session

    if proceed:
        if session.pending_plan:
            plan = [step.model_dump() for step in session.pending_plan.steps]
        else:
            plan = build_execution_plan_from_tool_calls(
                session, session.agent_state.pending_tool_calls
            )

        if not plan:
            with lock:
                session.pending_plan = None
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []
            return session

        with lock:
            session.projected_schedule             = compute_projected_schedule(plan=plan)
            session.background_job_plan            = plan
            session.background_job_index           = 0
            session.background_job_status          = "running"
            session.background_job_active          = True
            session.background_job_label           = "Initialising..."
            session.background_job_error           = None
            session.live_event_queue               = []
            session.pending_plan                   = None
            session.bo_iteration_counts            = {}
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
                _append_tool_response(
                    session, tc["id"], tc["function"]["name"],
                    json.dumps({"status": "aborted", "message": "User aborted the workflow."}),
                )
            session.agent_state.messages.append({"role": "user", "content": "abort"})
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []
            session.pending_plan                      = None
            session.equipment_status.llm              = True

        llm_plan(session)

        with lock:
            session.equipment_status.llm = False

    return session


def _consume_one_live_event(session: SessionModel) -> None:
    if not session.live_event_queue:
        return
    event = session.live_event_queue.pop(0)
    session.current_activity     = event.message
    session.background_job_label = event.message
    session.activity_log.append(f"[{event.category.upper()}] {event.message}")
    session.activity_log = session.activity_log[-50:]
    session.equipment_status = EquipmentStatusModel()
    eq_map = {
        "llm": "llm", "optimiser": "optimiser", "synthesiser": "synthesiser",
        "characteriser": "characteriser", "memory": "memory",
        "knowledge": "knowledge", "reporting": "reporting",
    }
    if eq_key := eq_map.get(event.equipment or ""):
        setattr(session.equipment_status, eq_key, True)


def _run_background_job(session_id: str) -> None:
    session      = get_session(session_id)
    lock         = _lock_for(session_id)
    dag_context: dict = {}

    with lock:
        for step in session.background_job_plan:
            if sid := step.get("step_id"):
                session.step_statuses[sid] = "pending"

    def set_step_status(step_id: str, status: str) -> None:
        with lock:
            session.step_statuses[step_id] = status

    def drain_events() -> None:
        while session.live_event_queue:
            with lock:
                if session.live_event_queue:
                    _consume_one_live_event(session)
            time.sleep(0.05)

    def mark_done(success: bool, error_msg: str = "") -> None:
        with lock:
            session.background_job_active = False
            session.background_job_status = "completed" if success else "failed"
            session.background_job_label  = None
            session.current_activity      = None
            session.equipment_status      = EquipmentStatusModel()
            session.pending_plan          = None
            # Keep projected_schedule intact so the Gantt shows actual vs projected

            if not success:
                session.background_job_error = error_msg
                session.agent_state.messages.append({
                    "role": "assistant",
                    "content": (
                        f"⚠️ Workflow stopped due to an error.\n\n"
                        f"**Details:** `{error_msg}`\n\n"
                        f"Results collected before the error have been saved."
                    ),
                })
            else:
                results  = session.agent_state.results_store
                n_evals  = sum(len(r.get("X", [])) for r in results)
                n_fails  = sum(r.get("failed_samples", 0) for r in results)
                best_obj = max((r.get("best_objective") or 0.0 for r in results), default=0.0)
                obj_label = (
                    session.extracted_campaign.objective_metric
                    if session.extracted_campaign else "objective"
                )
                conds_done = [
                    f"{r.get('condition_label')}={r.get('condition_value')}"
                    for r in results if r.get("X")
                ]
                is_plotter_job = any(
                    s.get("kind") == "generate_plot"
                    for s in session.background_job_plan
                )
                if is_plotter_job and session.show_plotter_image:
                    session.agent_state.messages.append({
                        "role": "assistant",
                        "content": f"Here is the summary figure:\n\n![Summary](/api/plot/{session.session_id})",
                    })
                elif n_evals > 0:
                    session.agent_state.messages.append({
                        "role": "assistant",
                        "content": (
                            f"✅ **Workflow complete.**\n\n"
                            f"| Metric | Value |\n|--------|-------|\n"
                            f"| Experiments run | {n_evals} |\n"
                            f"| Best {obj_label} | {best_obj:.4f} |\n"
                            f"| Failed steps | {n_fails} |\n"
                            f"| Conditions completed | {', '.join(conds_done) or 'none'} |\n\n"
                            f"Ask me to **generate a summary figure** or **analyse the results**."
                        ),
                    })

            session.live_event_queue.append(ExecutionEvent(
                event_type="job_complete",
                message="Job finished.",
                category="system",
                payload={
                    "background_job_active": False,
                    "background_job_status": session.background_job_status,
                },
            ))

    try:
        for step in session.background_job_plan:
            step_id = step.get("step_id", "")

            with lock:
                session.background_job_label = step.get("label") or step.get("kind", "running")

            set_step_status(step_id, "running")
            drain_events()

            try:
                result = execute_plan_step(session, step, query_database, dag_context)
                with lock:
                    session.agent_state.last_tool_result = result
                status = "failed" if result.get("status") == "error" else "completed"
                set_step_status(step_id, status)
            except Exception as step_err:
                with lock:
                    session.activity_log.append(f"[WARNING] Step '{step.get('kind')}' error: {step_err}")
                    session.activity_log = session.activity_log[-50:]
                set_step_status(step_id, "failed")

            with lock:
                session.background_job_index = sum(
                    1 for s in session.background_job_plan
                    if session.step_statuses.get(s.get("step_id", "")) == "completed"
                )

            drain_events()

        drain_events()
        mark_done(success=True)

    except Exception as fatal:
        mark_done(success=False, error_msg=f"{type(fatal).__name__}: {fatal}")


def register_artifact(session: SessionModel, name: str, kind: str, path: str) -> None:
    session.artifacts.append(ArtifactModel(name=name, kind=kind, path=path))
    session.artifacts = session.artifacts[-20:]


def session_state_payload(session: SessionModel) -> dict:
    results   = session.agent_state.results_store
    obj_label = (
        session.extracted_campaign.objective_metric
        if session.extracted_campaign else "Objective"
    )

    return {
        "session_id":                 session.session_id,
        "messages":                   session.agent_state.messages,
        "results_store":              results,
        "awaiting_confirmation":      session.agent_state.awaiting_confirmation,
        "pending_tool_calls":         session.agent_state.pending_tool_calls,
        "last_tool_result":           session.agent_state.last_tool_result,
        "last_tools_used":            session.agent_state.last_tools_used,
        "outstanding_tasks":          session.outstanding_tasks,
        "show_plotter_image":         session.show_plotter_image,
        "active_document_id":         session.active_document_id,
        "extracted_campaign":         (
            session.extracted_campaign.model_dump() if session.extracted_campaign else None
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
        "background_job_plan":        session.background_job_plan,
        "step_statuses":              session.step_statuses,
        "bo_iteration_counts":        session.bo_iteration_counts,
        "timeline":                   build_dynamic_timeline(session),
        "active_condition_key":       session.active_condition_key,
        "sample_registry":            [s.model_dump() for s in session.sample_registry],
        "pending_plan":               (
            session.pending_plan.model_dump() if session.pending_plan else None
        ),
        "optimiser_config":           session.optimiser_config.model_dump(),
        "projected_schedule":         [e.model_dump() for e in session.projected_schedule],
        "metric_labels": {
            "experiments": "Experiments",
            "best_result": f"Best {obj_label}",
            "conditions":  "Conditions Run",
            "failures":    "Failed Steps",
        },
        "resource_log": session.resource_log[-100:],
    }