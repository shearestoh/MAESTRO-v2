"""
Session management and workflow execution for MAESTRO.

All instrument actions require user approval via the workflow plan before
execution. Non-instrument actions execute immediately.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Dict

from app.core.database import ensure_db, init_db, query_database
from app.core.llm import _SYSTEM_PROMPT_CONTENT, llm_plan, _NON_INSTRUMENT_ACTIONS
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
    compute_projected_schedule,
)

SESSIONS:      Dict[str, SessionModel]    = {}
SESSION_LOCKS: Dict[str, threading.Lock] = {}

_INSTRUMENT_STEP_KINDS = {
    "synthesise",
    "characterise",
    "optimise_condition",
    "extract_feasibility",
}


def _lock_for(session_id: str) -> threading.Lock:
    if session_id not in SESSION_LOCKS:
        SESSION_LOCKS[session_id] = threading.Lock()
    return SESSION_LOCKS[session_id]


def _welcome_message() -> dict:
    return {
        "role": "assistant",
        "content": (
            "Welcome to **MAESTRO** — your agentic scientific orchestrator.\n\n"
            "You can:\n"
            "- Design and run experimental campaigns\n"
            "- Upload papers to the Library for reference and reproduction\n"
            "- Query and analyse your experimental results\n"
            "- Configure your lab via Lab Setup\n\n"
            "What would you like to explore today?"
        ),
    }


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
        current_mission="Awaiting instruction.",
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


def _plan_requires_approval(plan: list) -> bool:
    return any(step.get("kind") in _INSTRUMENT_STEP_KINDS for step in plan)


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

        # Build the execution plan from ALL pending tool calls
        plan = build_execution_plan_from_tool_calls(session, pending_calls)

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


def _handle_plan_requiring_approval(session, lock, plan, pending_calls, pending_names):
    has_plan_workflow = any(n == "plan_workflow" for n in pending_names)
    has_feasibility   = any(n == "extract_and_check_feasibility" for n in pending_names)

    if has_feasibility:
        with lock:
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []
            session.equipment_status = EquipmentStatusModel(knowledge=True)
            session.current_activity = "Checking feasibility..."

        for tc in pending_calls:
            if tc["function"]["name"] == "extract_and_check_feasibility":
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
                    "content":      json.dumps({"status": "running", "case_name": case_name}),
                })
                step = {"kind": "extract_feasibility", "case_name": case_name}
                try:
                    execute_plan_step(session, step, query_database)
                    _sync_condition_key(session)
                    _auto_build_campaign_plan(session)
                except Exception as e:
                    session.agent_state.messages.append({
                        "role": "assistant", "content": f"Error during feasibility check: `{e}`"
                    })

        with lock:
            session.equipment_status = EquipmentStatusModel()
            session.current_activity = None
        return

    if has_plan_workflow:
        from app.core.models import WorkflowPlan, WorkflowStep

        all_steps: list = []
        summaries: list[str] = []

        for tc in pending_calls:
            if tc["function"]["name"] != "plan_workflow":
                continue
            args = {}
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                pass

            summaries.append(args.get("summary", ""))

            for s in args.get("steps", []):
                # ── Defensive defaults — LLM sometimes omits these ────────────────
                if not s.get("label"):
                    # Generate a meaningful default label from available fields
                    kind  = s.get("kind", "step")
                    cond  = s.get("condition_label", "")
                    val   = s.get("condition_value", "")
                    opt   = s.get("optimiser_name", "")
                    if kind == "optimise_condition" and cond:
                        opt_display = f" [{opt}]" if opt else ""
                        s["label"] = f"Optimise {cond}={val}{opt_display}"
                    elif kind == "synthesise":
                        s["label"] = "Synthesise sample"
                    elif kind == "characterise":
                        s["label"] = "Characterise sample"
                    else:
                        s["label"] = kind.replace("_", " ").title()

                if not s.get("step_id"):
                    s["step_id"] = str(__import__("uuid").uuid4())[:8]

                # Stamp instrument_id
                raw_id = s.get("instrument_id") or s.get("instrument") or s.get("kind") or "unknown"
                s["instrument_id"] = str(raw_id)
                s.setdefault("status", "pending")
                s.setdefault("dependencies", [])

                # Stamp optimiser_name for optimise_condition steps
                if s.get("kind") == "optimise_condition":
                    if not s.get("condition_label"):
                        s["condition_label"] = "condition"
                    if s.get("condition_value") is None:
                        s["condition_value"] = 0.0
                    else:
                        s["condition_value"] = float(s["condition_value"])
                    if not s.get("free_params"):
                        s["free_params"] = []
                    if not s.get("objective_metric"):
                        s["objective_metric"] = "objective"
                    if not s.get("n_calls"):
                        s["n_calls"] = session.optimiser_config.n_calls
                    if not s.get("n_initial_points"):
                        s["n_initial_points"] = session.optimiser_config.n_initial_points
                    if not s.get("optimiser_name"):
                        s["optimiser_name"] = session.optimiser_config.name

                editable = []
                if s.get("kind") == "optimise_condition":
                    editable = ["n_calls", "n_initial_points", "condition_value"]
                    for fp in s.get("free_params", []):
                        editable += [f"{fp['name']}_min", f"{fp['name']}_max"]
                elif s.get("kind") in ("synthesise", "characterise"):
                    editable = list(s.get("params", {}).keys()) + list(s.get("conditions", {}).keys())
                s["editable_fields"] = editable

                try:
                    all_steps.append(WorkflowStep(**s))
                except Exception as e:
                    # Log and skip malformed steps rather than crashing
                    print(f"[WARN] Could not parse workflow step: {e} | step: {s}")
                    continue

        if not all_steps:
            # Nothing valid — let LLM know
            session.agent_state.messages.append({
                "role": "assistant",
                "content": "I couldn't build a valid workflow plan. Please try describing the steps again.",
            })
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
        plan_steps = [step.model_dump() for step in session.pending_plan.steps]
        session.projected_schedule = compute_projected_schedule(plan=plan_steps)

        # Inject tool responses for all plan_workflow calls
        for tc in pending_calls:
            if tc["function"]["name"] == "plan_workflow":
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         "plan_workflow",
                    "content":      json.dumps({
                        "status":  "pending_approval",
                        "message": "Workflow plan presented to user for approval.",
                    }),
                })
        return

    # Fallback: build plan from whatever instrument steps exist
    session.pending_plan = None
    with lock:
        steps = []
        for step in plan:
            if step.get("kind") in _INSTRUMENT_STEP_KINDS:
                steps.append(WorkflowStep(**{
                    k: v for k, v in step.items()
                    if k in WorkflowStep.model_fields
                }))
        if steps:
            session.pending_plan = WorkflowPlan(
                summary="Proposed workflow",
                steps=steps,
                source="agent",
            )


def _auto_build_campaign_plan(session):
    if not session.extracted_campaign:
        return
    c = session.extracted_campaign
    param_lookup = {p["name"].lower(): p for p in c.parameter_space}
    operating_conditions = c.operating_conditions

    from app.core.models import WorkflowPlan, WorkflowStep
    steps = []

    if not operating_conditions:
        step_id = str(uuid.uuid4())[:8]
        steps.append(WorkflowStep(
            step_id=step_id,
            kind="optimise_condition",
            label="BO Campaign",
            condition_label="run",
            condition_value=1.0,
            condition_unit="",
            free_params=_resolve_free_params_from_lookup(param_lookup),
            objective_metric=c.objective_metric or "objective",
            optimiser_name=session.optimiser_config.name,
            n_calls=session.optimiser_config.n_calls,
            n_initial_points=session.optimiser_config.n_initial_points,
            instrument_id="optimiser",
            status="pending",
        ))
    else:
        primary_oc = operating_conditions[0]
        session.active_condition_key = primary_oc.get("name", "condition")
        for oc in operating_conditions:
            oc_name   = oc.get("name", "condition")
            oc_unit   = oc.get("unit", "")
            oc_values = oc.get("values", [])
            for value in oc_values:
                step_id = str(uuid.uuid4())[:8]
                steps.append(WorkflowStep(
                    step_id=step_id,
                    kind="optimise_condition",
                    label=f"BO @ {oc_name}={value} {oc_unit}",
                    condition_label=oc_name,
                    condition_value=float(value),
                    condition_unit=oc_unit,
                    free_params=_resolve_free_params_from_lookup(param_lookup),
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


def _resolve_free_params_from_lookup(param_lookup: Dict[str, dict]) -> list:
    free_params = []
    for name, p in param_lookup.items():
        p_min = p.get("min")
        p_max = p.get("max")
        if p_min is None or p_max is None:
            continue
        free_params.append({
            "name": p.get("name", name),
            "min":  float(p_min),
            "max":  float(p_max),
            "unit": p.get("unit", ""),
        })
    return free_params


def _execute_non_instrument_actions(session, lock, plan, pending_calls):
    with lock:
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []

    dag_context = {}
    tool_results = []

    for tc in pending_calls:
        name = tc["function"]["name"]
        args = {}
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except Exception:
            pass

        step_kind_map = {
            "list_samples":   "list_samples",
            "generate_plot":  "generate_plot",
            "analyse_data":   "analyse_data",
            "query_database": "query_database",
        }

        if name not in step_kind_map:
            continue

        step = {
            "kind":          step_kind_map[name],
            "label":         args.get("description", name),
            "plot_code":     args.get("plot_code", ""),
            "analysis_code": args.get("analysis_code", ""),
            "sql":           args.get("sql", ""),
            "description":   args.get("description", ""),
        }

        try:
            result = execute_plan_step(session, step, query_database, dag_context)
        except Exception as e:
            result = {"status": "error", "message": str(e)}

        # Inject the tool response into the message history so the LLM can read it
        tool_response_content = json.dumps(result, default=str)
        session.agent_state.messages.append({
            "role":         "tool",
            "tool_call_id": tc["id"],
            "name":         name,
            "content":      tool_response_content,
        })
        tool_results.append((name, result))

    needs_followup = any(
        name == "query_database"
        for name, _ in tool_results
    )

    if needs_followup:
        with lock:
            session.equipment_status.llm = True
            session.current_activity     = "Interpreting results..."

        # Call LLM to interpret the query result and produce a user message
        llm_plan(session)

        with lock:
            session.equipment_status.llm = False
            session.current_activity     = None


def _sync_condition_key(session: SessionModel):
    if session.extracted_campaign:
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            session.active_condition_key = ocs[0].get("name", "condition")


def execute_plan(session_id: str, plan_dict: dict) -> SessionModel:
    from app.core.models import WorkflowPlan

    session = get_session(session_id)
    lock    = _lock_for(session_id)

    plan  = WorkflowPlan(**plan_dict)
    steps = [step.model_dump() for step in plan.steps]

    projected = compute_projected_schedule(plan=steps)

    with lock:
        session.background_job_plan        = steps
        session.background_job_index       = 0
        session.background_job_status      = "running"
        session.background_job_active      = True
        session.background_job_label       = "Initialising..."
        session.background_job_error       = None
        session.live_event_queue           = []
        session.pending_plan               = None
        session.projected_schedule         = projected
        session.bo_iteration_counts        = {}
        session.agent_state.awaiting_confirmation = False
        session.agent_state.pending_tool_calls    = []
        _inject_missing_tool_responses(session)

    threading.Thread(
        target=_run_background_job,
        args=(session_id,),
        daemon=True,
        name=f"maestro-plan-{session_id[:8]}",
    ).start()

    return session


def _consume_one_live_event(session: SessionModel):
    if not session.live_event_queue:
        return
    event = session.live_event_queue.pop(0)
    session.current_activity     = event.message
    session.background_job_label = event.message
    session.activity_log.append(f"[{event.category.upper()}] {event.message}")
    session.activity_log = session.activity_log[-50:]
    session.equipment_status = EquipmentStatusModel()
    eq_map = {
        "llm": "llm", "optimiser": "optimiser",
        "synthesiser": "synthesiser", "characteriser": "characteriser",
        "memory": "memory", "knowledge": "knowledge", "reporting": "reporting",
    }
    eq_key = eq_map.get(event.equipment or "")
    if eq_key:
        setattr(session.equipment_status, eq_key, True)


def _inject_missing_tool_responses(session: SessionModel):
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
                        "message": f"Tool '{tc_name}' executed.",
                    }),
                }))
                responded_ids.add(tc_id)
    for insert_idx, tool_msg in reversed(injections):
        messages.insert(insert_idx, tool_msg)


def _run_background_job(session_id: str):
    session     = get_session(session_id)
    lock        = _lock_for(session_id)
    dag_context: dict = {}

    instrument_locks: dict[str, threading.Lock] = {}

    def get_instrument_lock(instrument_id: str) -> threading.Lock:
        if instrument_id not in instrument_locks:
            instrument_locks[instrument_id] = threading.Lock()
        return instrument_locks[instrument_id]

    def set_step_status(step_id: str, status: str):
        with lock:
            session.step_statuses[step_id] = status

    def get_step_status(step_id: str) -> str:
        with lock:
            return session.step_statuses.get(step_id, "pending")

    def all_dependencies_complete(step: dict) -> bool:
        return all(
            get_step_status(dep_id) == "completed"
            for dep_id in step.get("dependencies", [])
        )

    with lock:
        for step in session.background_job_plan:
            step_id = step.get("step_id", "")
            if step_id:
                session.step_statuses[step_id] = "pending"

    def mark_done(success: bool, error_msg: str = ""):
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
                        f"⚠️ Workflow stopped due to an error.\n\n"
                        f"**Details:** `{error_msg}`\n\n"
                        f"Results collected before the error have been saved."
                    ),
                })
            else:
                results  = session.agent_state.results_store
                n_evals  = sum(len(r.get("X", [])) for r in results)
                n_fails  = sum(r.get("failed_samples", 0) for r in results)
                best_obj = max(
                    (r.get("best_objective") or 0.0 for r in results),
                    default=0.0,
                )
                obj_label  = (
                    session.extracted_campaign.objective_metric
                    if session.extracted_campaign else "objective"
                )
                cond_label = session.active_condition_key or "condition"
                conds_done = [
                    f"{r.get('condition_label', cond_label)}={r.get('condition_value', '?')}"
                    for r in results if r.get("X")
                ]

                is_plotter_job = any(
                    step.get("kind") in ("generate_plot",)
                    for step in session.background_job_plan
                )

                if is_plotter_job and session.show_plotter_image:
                    session.agent_state.messages.append({
                        "role":    "assistant",
                        "content": (
                            f"Here is the summary figure:\n\n"
                            f"![Summary](/api/plot/{session.session_id})"
                        ),
                    })
                elif n_evals > 0:
                    session.agent_state.messages.append({
                        "role":    "assistant",
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
                equipment=None,
                category="system",
                payload={
                    "background_job_active": False,
                    "background_job_status": session.background_job_status,
                },
            ))

    def execute_step_thread(step: dict):
        step_id       = step.get("step_id", "")
        instrument_id = step.get("instrument_id", "unknown")
        inst_lock     = get_instrument_lock(instrument_id)

        while not all_dependencies_complete(step):
            deps = step.get("dependencies", [])
            if any(get_step_status(d) == "failed" for d in deps):
                set_step_status(step_id, "skipped")
                return
            time.sleep(0.1)

        with inst_lock:
            set_step_status(step_id, "running")
            with lock:
                session.background_job_label = step.get("label") or step.get("kind", "running")

            try:
                result = execute_plan_step(session, step, query_database, dag_context)
                with lock:
                    session.agent_state.last_tool_result = result
                if result.get("status") == "error":
                    set_step_status(step_id, "failed")
                else:
                    set_step_status(step_id, "completed")
            except Exception as step_err:
                with lock:
                    session.activity_log.append(f"[WARNING] Step '{step.get('kind')}' error: {step_err}")
                    session.activity_log = session.activity_log[-50:]
                set_step_status(step_id, "failed")

        with lock:
            completed = sum(
                1 for s in session.background_job_plan
                if session.step_statuses.get(s.get("step_id", ""), "") == "completed"
            )
            session.background_job_index = completed

    try:
        plan  = session.background_job_plan
        steps = list(plan)

        stop_drain = threading.Event()

        def drain_events():
            while not stop_drain.is_set():
                with lock:
                    if session.live_event_queue:
                        _consume_one_live_event(session)
                time.sleep(0.08)

        event_thread = threading.Thread(
            target=drain_events, daemon=True,
            name=f"maestro-events-{session_id[:8]}"
        )
        event_thread.start()

        step_threads = []
        for step in steps:
            t = threading.Thread(
                target=execute_step_thread,
                args=(step,),
                daemon=True,
                name=f"maestro-step-{step.get('step_id', 'x')[:6]}",
            )
            step_threads.append(t)
            t.start()

        for t in step_threads:
            t.join()

        stop_drain.set()
        event_thread.join(timeout=1.0)

        time.sleep(0.3)
        while session.live_event_queue:
            with lock:
                _consume_one_live_event(session)
            time.sleep(0.05)

        mark_done(success=True)

    except Exception as fatal:
        mark_done(success=False, error_msg=f"{type(fatal).__name__}: {fatal}")


def confirm_pending(session_id: str, proceed: bool) -> SessionModel:
    session = get_session(session_id)
    lock    = _lock_for(session_id)

    has_pending = session.agent_state.awaiting_confirmation or session.pending_plan is not None

    with lock:
        if not has_pending:
            return session

    if proceed:
        pending_calls = session.agent_state.pending_tool_calls
        plan = build_execution_plan_from_tool_calls(session, pending_calls)

        if not plan:
            with lock:
                session.pending_plan = None
                session.agent_state.awaiting_confirmation = False
                session.agent_state.pending_tool_calls    = []
            return session

        projected = compute_projected_schedule(plan=plan)

        with lock:
            session.projected_schedule             = projected
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
                session.agent_state.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         tc["function"]["name"],
                    "content":      json.dumps({"status": "abort", "message": "User aborted."}),
                })
            session.agent_state.messages.append({"role": "user", "content": "abort"})
            session.agent_state.awaiting_confirmation = False
            session.agent_state.pending_tool_calls    = []
            session.pending_plan                      = None
            session.equipment_status.llm              = True

        llm_plan(session)

        with lock:
            session.equipment_status.llm = False

    return session


def register_artifact(session: SessionModel, name: str, kind: str, path: str):
    session.artifacts.append(ArtifactModel(name=name, kind=kind, path=path))
    session.artifacts = session.artifacts[-20:]


def session_state_payload(session: SessionModel) -> dict:
    results    = session.agent_state.results_store
    obj_label  = "Objective"
    cond_label = "Conditions"

    if session.extracted_campaign:
        obj_label = session.extracted_campaign.objective_metric or "Objective"
        ocs = session.extracted_campaign.operating_conditions
        if ocs:
            cond_label = ocs[0].get("name", "Conditions")

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