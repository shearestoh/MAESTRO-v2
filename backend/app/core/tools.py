"""
Execution engine for MAESTRO workflow steps.

Physical instrument steps are executed via adapters (app/adapters/).
The engine is instrument-agnostic: it reads instrument definitions from
the registry and dispatches to the appropriate adapter.

Step kinds:
  synthesise        — prepare a physical sample
  characterise      — measure a prepared sample
  optimise_condition — closed-loop Bayesian optimisation
  generate_plot     — matplotlib figure generation (subprocess-isolated)
  analyse_data      — numpy/scipy analysis (subprocess-isolated)
  query_database    — read-only SQL query
  list_samples      — sample registry lookup
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time as _time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import MAX_TOTAL_ATTEMPTS_FACTOR
from app.core.database import write_evaluation
from app.core.models import (
    ExecutionEvent,
    ProjectedScheduleEntry,
    Sample,
    SampleResult,
    generate_sample_id,
    make_result_entry,
)


# ── Adapter dispatch ──────────────────────────────────────────────────────────

def _get_adapter(instrument_name: str) -> Optional[Any]:
    from app.core.tool_registry import TOOL_REGISTRY
    inst = TOOL_REGISTRY.get_by_name(instrument_name)
    if inst and inst.adapter:
        try:
            return importlib.import_module(inst.adapter)
        except ImportError as e:
            print(f"[WARN] Could not load adapter {inst.adapter}: {e}")
    return None


def _instrument_failure_probability(instrument_name: str, params: Dict[str, float]) -> float:
    from app.core.tool_registry import TOOL_REGISTRY
    inst = TOOL_REGISTRY.get_by_name(instrument_name)
    if not inst or not inst.failure_modes:
        return 0.0
    adapter = _get_adapter(instrument_name)
    if adapter and hasattr(adapter, "failure_probability"):
        return adapter.failure_probability(params)
    non_certain = [fm.probability for fm in inst.failure_modes if fm.probability < 1.0]
    return max(non_certain) if non_certain else 0.0


def _execute_preparation(instrument_name: str, params: Dict[str, float]) -> Dict:
    adapter = _get_adapter(instrument_name)
    if adapter and hasattr(adapter, "prepare"):
        return adapter.prepare(params)
    fail_prob = _instrument_failure_probability(instrument_name, params)
    if np.random.rand() < fail_prob:
        return {"status": "failed", "reason": "Preparation failure", "failure_probability": fail_prob}
    return {"status": "ok", "params": params, "failure_probability": fail_prob}


def _execute_measurement(
    instrument_name: str,
    params:          Dict[str, float],
    conditions:      Dict[str, float],
) -> float:
    adapter = _get_adapter(instrument_name)
    if adapter and hasattr(adapter, "measure"):
        return adapter.measure(params, conditions)
    return float(np.random.normal(50.0, 2.0))


def _get_instrument_time_cost(instrument_name: str) -> float:
    from app.core.tool_registry import TOOL_REGISTRY
    return TOOL_REGISTRY.get_time_cost(instrument_name, default=0.0)


def _is_virtual_instrument(instrument_name: str) -> bool:
    from app.core.tool_registry import TOOL_REGISTRY
    inst = TOOL_REGISTRY.get_by_name(instrument_name)
    if inst and inst.adapter:
        return inst.adapter.startswith("app.adapters.")
    return False


def _apply_instrument_delay(instrument_name: str, time_cost_seconds: float) -> None:
    if time_cost_seconds > 0 and _is_virtual_instrument(instrument_name):
        _time.sleep(time_cost_seconds)



# ── Results store helpers ─────────────────────────────────────────────────────

def get_or_create_result_for_condition(
    results_store:   List[dict],
    condition_label: str,
    condition_value: float,
    optimiser_name:  str = "",
) -> dict:
    """
    Find an existing result entry matching condition + optimiser, or create a new one.
    Each (condition, optimiser) pair gets its own entry, allowing comparison across methods.
    """
    for r in results_store:
        if (
            r.get("condition_label") == condition_label
            and abs(r.get("condition_value", float("nan")) - condition_value) < 1e-9
            and r.get("optimiser_name", "") == optimiser_name
        ):
            return r
    entry = make_result_entry(condition_label, condition_value, optimiser_name)
    results_store.append(entry)
    return entry


def _log_resource(session, instrument_name: str, start_time: str, end_time: str):
    session.resource_log.append({
        "instrument": instrument_name,
        "start_time": start_time,
        "end_time":   end_time,
    })
    session.resource_log = session.resource_log[-500:]

def _deduct_resources(session, instrument_name: str) -> None:
    """Deduct consumables from SQLite and alert on low stock."""
    try:
        from app.core.database import get_all_resources, update_resource_stock
        resources = get_all_resources()
        warnings  = []
        for resource in resources:
            for rule in resource.get("consumption_rules", []):
                if rule.get("instrument_name") == instrument_name:
                    new_stock = max(0.0, resource["current_stock"] - rule["amount_per_use"])
                    update_resource_stock(resource["resource_id"], new_stock)
                    resource["current_stock"] = new_stock
                    min_s = resource.get("min_stock", 0)
                    if min_s > 0 and new_stock <= min_s:
                        warnings.append(
                            f"⚠️ Low stock: **{resource['name']}** — "
                            f"{new_stock:.1f} {resource['unit']} remaining "
                            f"(minimum: {min_s:.1f} {resource['unit']})"
                        )
        if warnings:
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": "\n".join(warnings),
            })
            session.live_event_queue.append(ExecutionEvent(
                event_type="resource_warning",
                message=f"Low stock after using {instrument_name}",
                equipment="memory",
                category="execution",
                payload={"warnings": warnings},
            ))
    except Exception as e:
        print(f"[WARN] Could not deduct resources for {instrument_name}: {e}")


def _resolve_ref(value: Any, context: Dict[str, Any]) -> Any:
    import re
    if not isinstance(value, str):
        return value
    match = re.compile(r"\{\{(\w+)\}\}").fullmatch(value.strip())
    if match:
        return context.get(match.group(1), value)
    return value


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── Projected Schedule ────────────────────────────────────────────────────────

def compute_projected_schedule(plan: List[dict]) -> List[ProjectedScheduleEntry]:
    from app.core.tool_registry import TOOL_REGISTRY
    from datetime import datetime as dt, timedelta, timezone

    now = dt.now(timezone.utc)

    def to_iso(d: dt) -> str:
        return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def get_duration_seconds(step: dict, resolved_instrument: str = "") -> float:
        """Get time cost for a step, using registry lookup for synthesise/characterise."""
        instrument_nm = step.get("instrument", "") or resolved_instrument
        if instrument_nm:
            cost = TOOL_REGISTRY.get_time_cost(instrument_nm, default=-1)
            if cost >= 0:
                return cost
        kind = step.get("kind", "")
        if kind == "synthesise":
            synth_list = TOOL_REGISTRY.list_by_sub_category("synthesis")
            if synth_list:
                return TOOL_REGISTRY.get_time_cost(synth_list[0].name, default=5.0)
            return 5.0
        if kind == "characterise":
            char_list = TOOL_REGISTRY.list_by_sub_category("characterisation")
            if char_list:
                return TOOL_REGISTRY.get_time_cost(char_list[0].name, default=8.0)
            return 8.0
        return 0.0

    step_end:        Dict[str, dt] = {}
    instrument_free: Dict[str, dt] = {}
    entries:         List[ProjectedScheduleEntry] = []

    for step in plan:
        step_id      = step.get("step_id") or ""
        kind         = step.get("kind", "")
        dependencies = step.get("dependencies", [])

        dep_end = max(
            (step_end.get(dep_id, now) for dep_id in dependencies),
            default=now,
        )

        if kind == "optimise_condition":
            n_calls = int(step.get("n_calls") or 10)

            synth_instruments = TOOL_REGISTRY.list_by_sub_category("synthesis")
            char_instruments  = TOOL_REGISTRY.list_by_sub_category("characterisation")
            synth_name = synth_instruments[0].name if synth_instruments else "Synthesiser"
            char_name  = char_instruments[0].name  if char_instruments  else "Characteriser"
            synth_time = TOOL_REGISTRY.get_time_cost(synth_name, default=5.0)
            char_time  = TOOL_REGISTRY.get_time_cost(char_name,  default=8.0)

            label_base = step.get("label", "Optimisation")
            cursor     = max(dep_end, instrument_free.get("optimiser", now), now)

            for i in range(n_calls):
                synth_start = max(cursor, instrument_free.get(synth_name, now))
                synth_end   = synth_start + timedelta(seconds=synth_time)
                entries.append(ProjectedScheduleEntry(
                    instrument_id=synth_name,
                    instrument_name=synth_name,
                    start_time=to_iso(synth_start),
                    end_time=to_iso(synth_end),
                    step_id=f"{step_id}-synth-{i}",
                    label=f"{label_base} iter {i + 1} — synthesise",
                    is_projected=True,
                ))
                instrument_free[synth_name] = synth_end

                char_start = max(synth_end, instrument_free.get(char_name, now))
                char_end   = char_start + timedelta(seconds=char_time)
                entries.append(ProjectedScheduleEntry(
                    instrument_id=char_name,
                    instrument_name=char_name,
                    start_time=to_iso(char_start),
                    end_time=to_iso(char_end),
                    step_id=f"{step_id}-char-{i}",
                    label=f"{label_base} iter {i + 1} — characterise",
                    is_projected=True,
                ))
                instrument_free[char_name] = char_end
                cursor = char_end

            step_end[step_id]            = cursor
            instrument_free["optimiser"] = cursor
            step["projected_start_time"] = to_iso(max(dep_end, now))
            step["projected_end_time"]   = to_iso(cursor)

        else:
            # Resolve the physical instrument name for synthesise/characterise steps.
            # The LLM may omit the instrument field — fall back to registry lookup
            # so the Task Schedule always shows the correct physical instrument row.
            explicit_instrument = step.get("instrument", "")

            if not explicit_instrument:
                if kind == "synthesise":
                    synth_list = TOOL_REGISTRY.list_by_sub_category("synthesis")
                    explicit_instrument = synth_list[0].name if synth_list else ""
                elif kind == "characterise":
                    char_list = TOOL_REGISTRY.list_by_sub_category("characterisation")
                    explicit_instrument = char_list[0].name if char_list else ""

            raw_instrument_id = (
                step.get("instrument_id")
                or explicit_instrument
                or kind
                or "unknown"
            )
            instrument_id   = str(raw_instrument_id) if raw_instrument_id is not None else "unknown"
            # Always use the resolved physical instrument name — never the step label
            instrument_name = explicit_instrument or instrument_id
            duration_s      = get_duration_seconds(step, resolved_instrument=instrument_name)

            inst_free  = instrument_free.get(instrument_id, now)
            proj_start = max(dep_end, inst_free, now)
            proj_end   = proj_start + timedelta(seconds=duration_s)

            step_end[step_id]              = proj_end
            instrument_free[instrument_id] = proj_end

            step["projected_start_time"] = to_iso(proj_start)
            step["projected_end_time"]   = to_iso(proj_end)

            if duration_s > 0 and instrument_id not in (
                "optimiser", "memory", "reporting", "knowledge", "unknown", ""
            ):
                entries.append(ProjectedScheduleEntry(
                    instrument_id=instrument_id,
                    instrument_name=instrument_name,
                    start_time=to_iso(proj_start),
                    end_time=to_iso(proj_end),
                    step_id=step_id,
                    label=step.get("label", step.get("kind", "")),
                    is_projected=True,
                ))

    return entries


# ── Dynamic plotting ──────────────────────────────────────────────────────────

_PLOT_TIMEOUT_SECONDS = 30

_PLOT_PREAMBLE = textwrap.dedent("""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import json, sys, os

data            = json.loads(os.environ.get("MAESTRO_DATA", "{}"))
results_store   = data.get("results_store", [])
sample_registry = data.get("sample_registry", [])
out_file        = os.environ.get("MAESTRO_OUT_FILE", "/tmp/maestro_plot.png")
""").strip()

_PLOT_FOOTER = textwrap.dedent("""
plt.tight_layout()
plt.savefig(out_file, dpi=150, bbox_inches="tight")
plt.close("all")
print(f"SAVED:{out_file}")
""").strip()


import re as _re

def _sanitise_plot_code(code: str) -> str:
    """
    Remove calls that conflict with the script footer:
    plt.savefig, plt.show, plt.close, plt.tight_layout.
    These are injected by the footer to ensure consistent output.
    """
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if _re.match(
            r'plt\.(savefig|show|close|tight_layout)\s*\(',
            stripped,
        ):
            continue
        lines.append(line)
    return "\n".join(lines)


def generate_plot(session, plot_code: str, out_file: Optional[str] = None) -> str:
    if out_file is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="maestro_plot_", delete=False)
        out_file = tmp.name
        tmp.close()

    sanitised_code = _sanitise_plot_code(plot_code)

    data_payload = {
        "results_store":   session.agent_state.results_store,
        "sample_registry": [s.model_dump() for s in session.sample_registry],
    }

    full_script = f"{_PLOT_PREAMBLE}\n\n{sanitised_code}\n\n{_PLOT_FOOTER}"
    script_file = tempfile.NamedTemporaryFile(
        suffix=".py", prefix="maestro_plot_script_",
        delete=False, mode="w", encoding="utf-8",
    )
    script_file.write(full_script)
    script_file.close()

    env = os.environ.copy()
    env["MAESTRO_DATA"]     = json.dumps(data_payload)
    env["MAESTRO_OUT_FILE"] = out_file

    try:
        result = subprocess.run(
            [sys.executable, script_file.name],
            capture_output=True, text=True,
            timeout=_PLOT_TIMEOUT_SECONDS, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Plot script failed:\n{result.stderr[:800]}")
        if not os.path.exists(out_file):
            raise RuntimeError("Plot script ran but did not save output file")
        return out_file
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Plot script timed out after {_PLOT_TIMEOUT_SECONDS}s")
    finally:
        try:
            os.unlink(script_file.name)
        except Exception:
            pass


def analyse_data(session, analysis_code: str) -> str:
    data_payload = {
        "results_store":   session.agent_state.results_store,
        "sample_registry": [s.model_dump() for s in session.sample_registry],
    }

    preamble = textwrap.dedent("""
import numpy as np
import json, os
from scipy import stats

data            = json.loads(os.environ.get("MAESTRO_DATA", "{}"))
results_store   = data.get("results_store", [])
sample_registry = data.get("sample_registry", [])
""").strip()

    full_script = f"{preamble}\n\n{analysis_code}"
    script_file = tempfile.NamedTemporaryFile(
        suffix=".py", prefix="maestro_analysis_",
        delete=False, mode="w", encoding="utf-8",
    )
    script_file.write(full_script)
    script_file.close()

    env = os.environ.copy()
    env["MAESTRO_DATA"] = json.dumps(data_payload)

    try:
        result = subprocess.run(
            [sys.executable, script_file.name],
            capture_output=True, text=True,
            timeout=_PLOT_TIMEOUT_SECONDS, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Analysis script failed:\n{result.stderr[:800]}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Analysis script timed out after {_PLOT_TIMEOUT_SECONDS}s")
    finally:
        try:
            os.unlink(script_file.name)
        except Exception:
            pass


# ── Sample Registry operations ────────────────────────────────────────────────

def synthesise_step(session, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
    params     = step.get("params", {})
    instrument = step.get("instrument", "")

    if not instrument:
        from app.core.tool_registry import TOOL_REGISTRY
        synthesis_instruments = TOOL_REGISTRY.list_by_sub_category("synthesis")
        instrument = synthesis_instruments[0].name if synthesis_instruments else "Unknown"

    produces  = step.get("produces", "sample_id")
    time_cost = _get_instrument_time_cost(instrument)

    session.live_event_queue.append(ExecutionEvent(
        event_type="synthesiser_start",
        message=f"Synthesising sample on {instrument}: " + ", ".join(f"{k}={v}" for k, v in params.items()),
        equipment="synthesiser",
        category="execution",
        payload={"params": params, "instrument": instrument},
    ))

    start_time = _now()
    _apply_instrument_delay(instrument, time_cost)
    result    = _execute_preparation(instrument, params)
    end_time  = _now()
    _log_resource(session, instrument, start_time, end_time)

    sample_id = generate_sample_id(session)
    timestamp = _now()

    if result["status"] != "ok":
        failed_sample = Sample(
            sample_id=sample_id,
            params=params,
            prepared_by=instrument,
            status="failed",
            prepared_at=timestamp,
            failure_reason=result.get("reason", "Unknown failure"),
        )
        session.sample_registry.append(failed_sample)
        session.live_event_queue.append(ExecutionEvent(
            event_type="synthesiser_fail",
            message=f"Sample {sample_id} failed: {result.get('reason', 'defect')}",
            equipment="synthesiser",
            category="execution",
            payload={"sample_id": sample_id, "params": params},
        ))
        return {"status": "failed", "sample_id": sample_id, "reason": result.get("reason")}

    new_sample = Sample(
        sample_id=sample_id,
        params=params,
        prepared_by=instrument,
        status="prepared",
        prepared_at=timestamp,
    )
    session.sample_registry.append(new_sample)
    context[produces] = sample_id
    _deduct_resources(session, instrument) 

    session.live_event_queue.append(ExecutionEvent(
        event_type="synthesiser_done",
        message=f"Sample {sample_id} synthesised and stored.",
        equipment="synthesiser",
        category="execution",
        payload={"sample_id": sample_id, "params": params},
    ))
    session.agent_state.messages.append({
        "role":    "assistant",
        "content": (
            f"✅ **Sample `{sample_id}` synthesised**\n\n"
            + "\n".join(f"- **{k}:** {v}" for k, v in params.items())
            + f"\n\nStored in lab inventory."
        ),
    })
    return {"status": "ok", "sample_id": sample_id, "params": params}


def characterise_step(session, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
    sample_ref = _resolve_ref(step.get("sample_ref", ""), context)
    conditions = step.get("conditions", {})
    measures   = step.get("measures", "objective")
    instrument = step.get("instrument", "")

    if not instrument:
        from app.core.tool_registry import TOOL_REGISTRY
        char_instruments = TOOL_REGISTRY.list_by_sub_category("characterisation")
        instrument = char_instruments[0].name if char_instruments else "Unknown"

    sample = next((s for s in session.sample_registry if s.sample_id == sample_ref), None)
    if sample is None:
        session.live_event_queue.append(ExecutionEvent(
            event_type="characteriser_fail",
            message=f"Sample {sample_ref} not found.",
            equipment="characteriser",
            category="execution",
            payload={"sample_ref": sample_ref},
        ))
        return {"status": "error", "message": f"Sample {sample_ref} not found"}

    if sample.status == "failed":
        return {"status": "error", "message": f"Sample {sample_ref} failed synthesis"}

    time_cost = _get_instrument_time_cost(instrument)

    session.live_event_queue.append(ExecutionEvent(
        event_type="characteriser_start",
        message=f"Characterising {sample_ref} on {instrument}: " + ", ".join(f"{k}={v}" for k, v in conditions.items()),
        equipment="characteriser",
        category="execution",
        payload={"sample_id": sample_ref, "conditions": conditions},
    ))

    start_time = _now()
    _apply_instrument_delay(instrument, time_cost)
    value     = _execute_measurement(instrument, sample.params, conditions)
    end_time  = _now()
    _log_resource(session, instrument, start_time, end_time)

    timestamp = _now()
    result = SampleResult(
        tested_by=instrument,
        conditions=conditions,
        outputs={measures: value},
        tested_at=timestamp,
    )
    sample.results.append(result)
    sample.status = "tested"

    condition_name  = list(conditions.keys())[0]  if conditions else "condition"
    condition_value = list(conditions.values())[0] if conditions else 0.0
    write_evaluation(
        condition_name=condition_name,
        condition_value=condition_value,
        parameters=sample.params,
        objective_name=measures,
        objective_value=value,
        timestamp=timestamp,
    )

    session.live_event_queue.append(ExecutionEvent(
        event_type="characteriser_done",
        message=f"{sample_ref}: {measures} = {value:.4f}",
        equipment="characteriser",
        category="analysis",
        payload={"sample_id": sample_ref, "conditions": conditions, "outputs": {measures: value}},
    ))
    session.live_event_queue.append(ExecutionEvent(
        event_type="memory_update",
        message="Result recorded to database.",
        equipment="memory",
        category="analysis",
        payload={},
    ))
    cond_str = ", ".join(f"{k} = {v}" for k, v in conditions.items()) if conditions else "no conditions set"
    session.agent_state.messages.append({
        "role":    "assistant",
        "content": (
            f"⚡ **`{sample_ref}` characterised**"
            + (f" ({cond_str})" if conditions else "")
            + f"\n\n**{measures}:** {value:.4f}"
        ),
    })
    return {"status": "ok", "sample_id": sample_ref, "conditions": conditions, "outputs": {measures: value}}


def list_samples_step(session) -> Dict[str, Any]:
    """Return sample inventory as structured data — do NOT append assistant message directly."""
    samples = session.sample_registry
    if not samples:
        return {
            "status":  "ok",
            "count":   0,
            "samples": [],
            "message": "No samples in the lab inventory yet.",
        }
    rows = []
    for s in samples:
        params_str  = ", ".join(f"{k}={v}" for k, v in s.params.items())
        results_str = f"{len(s.results)} test(s)" if s.results else "untested"
        rows.append({
            "sample_id":   s.sample_id,
            "params":      params_str,
            "status":      s.status,
            "prepared_at": s.prepared_at[:16] if s.prepared_at else "",
            "results":     results_str,
        })
    return {"status": "ok", "count": len(samples), "samples": rows}


# ── BO execution engine ───────────────────────────────────────────────────────

def run_optimise_condition(
    session,
    step:          dict,
    results_store: List[dict],
) -> Dict[str, Any]:
    """
    Execute a closed-loop Bayesian optimisation campaign.
    Runs synchronously, emitting live events to session.live_event_queue.
    """
    condition_label     = step.get("condition_label") or "condition"
    condition_value_raw = step.get("condition_value")
    condition_value     = float(condition_value_raw) if condition_value_raw is not None else 0.0
    free_params         = step.get("free_params") or []
    objective_metric    = step.get("objective_metric") or "objective"
    n_calls             = int(step.get("n_calls") or session.optimiser_config.n_calls)
    n_init              = int(step.get("n_initial_points") or session.optimiser_config.n_initial_points)
    conditions          = {condition_label: condition_value}
    optimiser_name      = step.get("optimiser_name") or session.optimiser_config.name

    if not free_params:
        session.live_event_queue.append(ExecutionEvent(
            event_type="optimiser_error",
            message="BO step has no free parameters defined. Please specify parameters to optimise.",
            equipment="optimiser",
            category="planning",
            payload={},
        ))
        session.agent_state.messages.append({
            "role": "assistant",
            "content": (
                "⚠️ The optimisation step has no free parameters defined. "
                "Please specify which parameters to optimise and their ranges."
            ),
        })
        return {"status": "error", "message": "No free parameters defined"}

    from app.core.tool_registry import TOOL_REGISTRY
    synthesis_instruments        = TOOL_REGISTRY.list_by_sub_category("synthesis")
    characterisation_instruments = TOOL_REGISTRY.list_by_sub_category("characterisation")
    synth_name = synthesis_instruments[0].name        if synthesis_instruments        else "Synthesis"
    char_name  = characterisation_instruments[0].name if characterisation_instruments else "Characterisation"
    synth_time = _get_instrument_time_cost(synth_name)
    char_time  = _get_instrument_time_cost(char_name)

    param_summary = ", ".join(
        f"{p['name']} [{p['min']}–{p['max']} {p.get('unit','')}]"
        for p in free_params
    )
    session.live_event_queue.append(ExecutionEvent(
        event_type="optimiser_start",
        message=(
            f"Starting {optimiser_name}: {condition_label}={condition_value} | "
            f"Optimising: {param_summary} | Objective: {objective_metric}"
        ),
        equipment="optimiser",
        category="planning",
        payload={"condition_label": condition_label, "condition_value": condition_value},
    ))

    res = get_or_create_result_for_condition(
        results_store,
        condition_label,
        condition_value,
        optimiser_name=optimiser_name,
    )
    if not res.get("param_names"):
        res["param_names"] = [p["name"] for p in free_params]

    from app.optimisers.catalogue import get_optimiser
    opt    = get_optimiser(optimiser_name)
    bounds = [(float(p["min"]), float(p["max"])) for p in free_params]
    opt.initialise(bounds=bounds, n_initial_points=min(n_init, n_calls), random_state=42)

    step_id        = step.get("step_id", "")
    best_objective = res.get("best_objective")
    successes      = 0
    attempts       = 0
    failed_samples = int(res.get("failed_samples", 0))
    max_attempts   = max(n_calls, n_calls * MAX_TOTAL_ATTEMPTS_FACTOR)

    while successes < n_calls and attempts < max_attempts:
        suggestion = opt.suggest()
        param_dict = {p["name"]: float(v) for p, v in zip(free_params, suggestion)}
        attempts  += 1

        param_str = ", ".join(f"{k}={v:.3f}" for k, v in param_dict.items())
        session.live_event_queue.append(ExecutionEvent(
            event_type="candidate_proposed",
            message=f"{optimiser_name} proposes: {param_str}",
            equipment="optimiser",
            category="planning",
            payload={"params": param_dict},
        ))

        session.live_event_queue.append(ExecutionEvent(
            event_type="synthesiser_start",
            message=f"Synthesising sample: {param_str}",
            equipment="synthesiser",
            category="execution",
            payload={"params": param_dict},
        ))

        start_time  = _now()
        _apply_instrument_delay(synth_name, synth_time)
        prep_result = _execute_preparation(synth_name, param_dict)
        end_time    = _now()
        _log_resource(session, synth_name, start_time, end_time)

        if prep_result["status"] != "ok":
            failed_samples += 1
            failed_id = generate_sample_id(session)
            session.sample_registry.append(Sample(
                sample_id=failed_id,
                params=param_dict,
                prepared_by=synth_name,
                status="failed",
                prepared_at=_now(),
                failure_reason="Synthesis defect",
                notes=f"BO iteration @ {condition_label}={condition_value} [{optimiser_name}]",
            ))
            session.live_event_queue.append(ExecutionEvent(
                event_type="synthesiser_fail",
                message=f"Sample failed (p={prep_result['failure_probability']:.0%}). Retrying.",
                equipment="synthesiser",
                category="execution",
                payload={"params": param_dict},
            ))
            continue

        bo_sample_id = generate_sample_id(session)
        bo_sample    = Sample(
            sample_id=bo_sample_id,
            params=param_dict,
            prepared_by=synth_name,
            status="prepared",
            prepared_at=_now(),
            notes=f"BO iter {successes + 1} @ {condition_label}={condition_value} [{optimiser_name}]",
        )
        session.sample_registry.append(bo_sample)

        session.live_event_queue.append(ExecutionEvent(
            event_type="characteriser_start",
            message=f"Characterising {bo_sample_id} at {condition_label}={condition_value}...",
            equipment="characteriser",
            category="execution",
            payload={"sample_id": bo_sample_id},
        ))

        start_time      = _now()
        _apply_instrument_delay(char_name, char_time)
        objective_value = _execute_measurement(char_name, param_dict, conditions)
        end_time        = _now()
        _log_resource(session, char_name, start_time, end_time)

        opt.update(suggestion, objective_value)
        successes += 1

        bo_sample.status = "tested"
        bo_sample.results.append(SampleResult(
            tested_by=char_name,
            conditions=dict(conditions),
            outputs={objective_metric: objective_value},
            tested_at=_now(),
        ))

        write_evaluation(
            condition_name=condition_label,
            condition_value=condition_value,
            parameters=param_dict,
            objective_name=objective_metric,
            objective_value=objective_value,
            timestamp=_now(),
        )

        res["X"].append(list(suggestion))
        res["y"].append(objective_value)
        res["failed_samples"] = failed_samples
        res["attempts"]       = attempts
        res["param_names"]    = [p["name"] for p in free_params]

        if best_objective is None or objective_value > best_objective:
            best_objective        = objective_value
            res["best_objective"] = objective_value
            res["best_params"]    = dict(param_dict)

        # Update live iteration counter for frontend progress display
        if step_id:
            session.bo_iteration_counts[step_id] = successes

        session.live_event_queue.append(ExecutionEvent(
            event_type="characteriser_done",
            message=f"Iteration {successes}/{n_calls}: {objective_metric} = {objective_value:.4f}",
            equipment="characteriser",
            category="analysis",
            payload={
                "objective_value": objective_value,
                "params":          param_dict,
                "iteration":       successes,
                "n_calls":         n_calls,
            },
        ))
        session.live_event_queue.append(ExecutionEvent(
            event_type="memory_update",
            message="Result recorded to database.",
            equipment="memory",
            category="analysis",
            payload={},
        ))

    best_str = f"{best_objective:.4f}" if best_objective is not None else "N/A"
    session.live_event_queue.append(ExecutionEvent(
        event_type="optimiser_complete",
        message=(
            f"{optimiser_name} complete: {condition_label}={condition_value}. "
            f"Best {objective_metric}: {best_str}"
        ),
        equipment="optimiser",
        category="planning",
        payload={
            "condition_label":  condition_label,
            "condition_value":  condition_value,
            "best_objective":   best_objective,
            "objective_metric": objective_metric,
            "optimiser_name":   optimiser_name,
        },
    ))
    return {"status": "ok", "best_objective": best_objective, "n_evaluations": successes}


# ── Plan execution ────────────────────────────────────────────────────────────

def execute_plan_step(
    session,
    step:              dict,
    query_database_fn,
    dag_context:       Optional[Dict[str, Any]] = None,
) -> Dict:
    if dag_context is None:
        dag_context = {}

    results_store = session.agent_state.results_store
    kind          = step["kind"]

    if kind == "narration":
        session.live_event_queue.append(ExecutionEvent(
            event_type="narration",
            message=step.get("message", step.get("label", "")),
            equipment=step.get("equipment"),
            category=step.get("category", "knowledge"),
            payload={},
        ))
        return {"status": "ok"}

    if kind == "extract_feasibility":
        from app.core.extraction import extract_case_study_to_campaign
        case_name = step.get("case_name", "Case Study")
        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_read",
            message=f"Extracting '{case_name}' from paper...",
            equipment="knowledge",
            category="knowledge",
            payload={},
        ))
        if not session.active_document_id:
            session.agent_state.messages.append({
                "role": "assistant",
                "content": "Please upload a paper first.",
            })
            return {"status": "error", "message": "No document uploaded"}
        try:
            extraction = extract_case_study_to_campaign(session.active_document_id, case_name)
            session.extracted_campaign = extraction.campaign
            ocs = extraction.campaign.operating_conditions
            if ocs:
                session.active_condition_key = ocs[0].get("name", "condition")
            feasibility = extraction.campaign.capability_match
            is_feasible = feasibility.get("feasible", False)
            session.live_event_queue.append(ExecutionEvent(
                event_type="feasibility_result",
                message=f"Feasibility: {'✅ Feasible' if is_feasible else '⚠️ Partial'}",
                equipment="knowledge",
                category="knowledge",
                payload={},
            ))
            missing_p = feasibility.get("missing_params", [])
            missing_o = feasibility.get("missing_outputs", [])
            lines = [
                f"## Feasibility Report: {case_name}\n",
                f"**Campaign:** {extraction.campaign.title}",
                f"**Objective:** `{extraction.campaign.objective_metric}`\n",
                "### Free Parameters",
            ]
            for p in extraction.campaign.parameter_space:
                ok = p["name"] not in missing_p
                lines.append(
                    f"- `{p['name']}` ({p.get('min')}–{p.get('max')} {p.get('unit', '')}) "
                    f"{'✅' if ok else '❌ not available'}"
                )
            if extraction.campaign.operating_conditions:
                lines.append("\n### Operating Conditions")
                for oc in extraction.campaign.operating_conditions:
                    vals = oc.get("values", [])
                    lines.append(
                        f"- `{oc['name']}`: {vals} {oc.get('unit', '')} "
                        f"→ {len(vals)} separate BO campaigns"
                    )
            lines += [
                f"\n### Output",
                f"- `{extraction.campaign.objective_metric}` "
                f"{'✅ measurable' if not missing_o else '❌ not measurable'}",
                f"\n### Verdict",
            ]
            if is_feasible:
                n_runs = sum(len(oc.get("values", [])) for oc in extraction.campaign.operating_conditions) or 1
                lines.append(
                    f"✅ **Fully reproducible.** This will run **{n_runs} separate BO campaign(s)**."
                )
            else:
                lines.append(f"⚠️ **Partially feasible.** Missing: {missing_p + missing_o}.")
            if extraction.campaign.assumptions:
                lines.append("\n### Assumptions")
                for a in extraction.campaign.assumptions:
                    lines.append(f"- {a}")
            session.agent_state.messages.append({"role": "assistant", "content": "\n".join(lines)})
            return {"status": "ok", "feasible": is_feasible}
        except Exception as e:
            session.agent_state.messages.append({
                "role": "assistant", "content": f"Error extracting campaign: `{e}`"
            })
            return {"status": "error", "message": str(e)}

    if kind == "synthesise":
        return synthesise_step(session, step, dag_context)

    if kind == "characterise":
        return characterise_step(session, step, dag_context)

    if kind == "list_samples":
        return list_samples_step(session)

    if kind == "optimise_condition":
        return run_optimise_condition(session, step, results_store)

    if kind == "generate_plot":
        session.live_event_queue.append(ExecutionEvent(
            event_type="plotter_start",
            message="Generating figure...",
            equipment="reporting",
            category="reporting",
            payload={},
        ))
        plot_code = step.get("plot_code", "") or _default_summary_plot_code()

        def _try_plot(code: str) -> str | None:
            try:
                return generate_plot(session, code)
            except Exception:
                return None

        fig_path = _try_plot(plot_code)
        if fig_path is None and plot_code != _default_summary_plot_code():
            fig_path = _try_plot(_default_summary_plot_code())

        if fig_path:
            session.show_plotter_image = fig_path
            session.live_event_queue.append(ExecutionEvent(
                event_type="plotter_done",
                message="Figure ready.",
                equipment="reporting",
                category="reporting",
                payload={},
            ))
            return {"status": "ok", "figure_path": fig_path}
        else:
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": "⚠️ Figure generation failed. Try asking for a simpler plot or check that there are results to display.",
            })
            session.live_event_queue.append(ExecutionEvent(
                event_type="plotter_fail",
                message="Figure generation failed.",
                equipment="reporting",
                category="reporting",
                payload={},
            ))
            return {"status": "error", "message": "Figure generation failed"}

    if kind == "analyse_data":
        session.live_event_queue.append(ExecutionEvent(
            event_type="analysis_start",
            message="Running data analysis...",
            equipment="reporting",
            category="reporting",
            payload={},
        ))
        analysis_code = step.get("analysis_code", "")
        if not analysis_code:
            return {"status": "error", "message": "No analysis code provided"}
        try:
            output = analyse_data(session, analysis_code)
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": f"**Analysis results:**\n\n```\n{output}\n```",
            })
            session.live_event_queue.append(ExecutionEvent(
                event_type="analysis_done",
                message="Analysis complete.",
                equipment="reporting",
                category="reporting",
                payload={},
            ))
            return {"status": "ok", "output": output}
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}

    if kind == "query_database":
        session.live_event_queue.append(ExecutionEvent(
            event_type="memory_query",
            message="Querying database...",
            equipment="memory",
            category="analysis",
            payload={},
        ))
        result = query_database_fn(step.get("sql", ""))
        result["query_description"] = step.get("description", "")
        return result

    return {"status": "error", "message": f"Unknown step kind: {kind}"}


def _default_summary_plot_code() -> str:
    return textwrap.dedent("""
# Generic summary plot — adapts to whatever data is available.
# Inspects results_store structure at runtime; never assumes field names.

import math

def safe_float(v):
    try: return float(v)
    except: return None

if not results_store:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.text(0.5, 0.5, "No experimental results yet.", ha="center", va="center",
            transform=ax.transAxes, fontsize=12, color="#94a3b8")
    ax.set_axis_off()
else:
    # ── Discover data structure dynamically ──────────────────────────────────
    all_param_names = []
    for r in results_store:
        for p in r.get("param_names", []):
            if p not in all_param_names:
                all_param_names.append(p)

    has_X         = any(len(r.get("X", [])) > 0 for r in results_store)
    has_y         = any(len(r.get("y", [])) > 0 for r in results_store)
    has_best      = any(r.get("best_objective") is not None for r in results_store)
    n_params      = len(all_param_names)
    n_results     = len(results_store)
    cond_label    = results_store[0].get("condition_label", "condition") if results_store else "condition"
    optimisers    = list(dict.fromkeys(r.get("optimiser_name", "") for r in results_store))

    # ── Layout: decide number of panels ──────────────────────────────────────
    panels = []
    if has_y:
        panels.append("convergence")   # best-so-far vs iteration
    if has_best and n_results > 1:
        panels.append("optimality")    # best objective vs condition
    if has_X and n_params >= 2:
        panels.append("scatter_2d")    # 2D parameter space coloured by objective
    if has_X and n_params == 1:
        panels.append("scatter_1d")    # 1D: param vs objective
    if not panels:
        panels.append("summary_text")  # fallback: text summary

    n_cols = min(3, len(panels))
    n_rows = math.ceil(len(panels) / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5.5 * n_cols, 4 * n_rows), squeeze=False)
    axes_flat = axes.ravel()
    palette   = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]

    for panel_idx, panel in enumerate(panels):
        ax = axes_flat[panel_idx]

        if panel == "convergence":
            # Best-so-far vs iteration for each (condition, optimiser) pair
            for ri, r in enumerate(results_store):
                y_vals = r.get("y", [])
                if not y_vals:
                    continue
                best_so_far = [max(y_vals[:i+1]) for i in range(len(y_vals))]
                cval        = r.get("condition_value", ri)
                opt_name    = r.get("optimiser_name", "")
                lbl         = f"{cond_label}={cval}"
                if opt_name:
                    lbl += f" [{opt_name}]"
                col = palette[ri % len(palette)]
                ax.plot(range(1, len(best_so_far) + 1), best_so_far,
                        "o-", color=col, linewidth=1.8, markersize=4, label=lbl, alpha=0.85)
            ax.set_title("Convergence (best so far)", fontsize=9)
            ax.set_xlabel("Iteration", fontsize=8)
            ax.set_ylabel("Best objective", fontsize=8)
            ax.legend(fontsize=7, loc="lower right")
            ax.grid(True, alpha=0.25)

        elif panel == "optimality":
            # Best objective vs condition value, grouped by optimiser
            for oi, opt_name in enumerate(optimisers):
                opt_results = sorted(
                    [r for r in results_store
                     if r.get("optimiser_name", "") == opt_name
                     and r.get("best_objective") is not None],
                    key=lambda r: safe_float(r.get("condition_value", 0)) or 0,
                )
                if not opt_results:
                    continue
                xs  = [safe_float(r.get("condition_value", 0)) or 0 for r in opt_results]
                ys  = [r["best_objective"] for r in opt_results]
                col = palette[oi % len(palette)]
                lbl = opt_name or "unknown"
                ax.plot(xs, ys, "o-", color=col, linewidth=2, markersize=8,
                        label=lbl, alpha=0.85)
            ax.set_title("Optimality path", fontsize=9)
            ax.set_xlabel(cond_label, fontsize=8)
            ax.set_ylabel("Best objective", fontsize=8)
            ax.legend(fontsize=7)
            ax.grid(True, alpha=0.25)

        elif panel == "scatter_2d":
            # First two parameters coloured by objective, one subplot per result
            # If multiple results, show the first one that has data
            plotted = False
            for ri, r in enumerate(results_store):
                X_raw = r.get("X", [])
                y_raw = r.get("y", [])
                p_names = r.get("param_names", all_param_names)
                if not X_raw or not y_raw or len(p_names) < 2:
                    continue
                X = np.array(X_raw)
                y = np.array(y_raw)
                if X.ndim != 2 or X.shape[1] < 2:
                    continue
                sc = ax.scatter(X[:, 0], X[:, 1], c=y, cmap="plasma", s=40, alpha=0.8)
                bp = r.get("best_params", {})
                bx = safe_float(bp.get(p_names[0]))
                by = safe_float(bp.get(p_names[1]))
                if bx is not None and by is not None:
                    ax.scatter([bx], [by], facecolors="none", edgecolors="black",
                               s=120, linewidths=1.5, zorder=5, label="Best")
                    ax.legend(fontsize=7)
                cval = r.get("condition_value", ri)
                ax.set_title(f"{cond_label}={cval}", fontsize=9)
                ax.set_xlabel(p_names[0], fontsize=8)
                ax.set_ylabel(p_names[1], fontsize=8)
                fig.colorbar(sc, ax=ax).set_label("Objective", fontsize=7)
                plotted = True
                break  # one panel for 2D scatter
            if not plotted:
                ax.set_axis_off()
                ax.text(0.5, 0.5, "Insufficient data for 2D scatter",
                        ha="center", va="center", transform=ax.transAxes, fontsize=8, color="#94a3b8")

        elif panel == "scatter_1d":
            # Single parameter vs objective
            for ri, r in enumerate(results_store):
                X_raw   = r.get("X", [])
                y_raw   = r.get("y", [])
                p_names = r.get("param_names", all_param_names)
                if not X_raw or not y_raw:
                    continue
                X   = np.array(X_raw)
                y   = np.array(y_raw)
                col = palette[ri % len(palette)]
                cval = r.get("condition_value", ri)
                lbl  = f"{cond_label}={cval}"
                x_vals = X[:, 0] if X.ndim == 2 else X
                ax.scatter(x_vals, y, color=col, s=40, alpha=0.7, label=lbl)
            ax.set_title("Parameter vs Objective", fontsize=9)
            ax.set_xlabel(all_param_names[0] if all_param_names else "parameter", fontsize=8)
            ax.set_ylabel("Objective", fontsize=8)
            ax.legend(fontsize=7)
            ax.grid(True, alpha=0.25)

        elif panel == "summary_text":
            ax.set_axis_off()
            lines = ["Summary"]
            for r in results_store:
                best = r.get("best_objective")
                n    = len(r.get("X", []))
                cval = r.get("condition_value", "?")
                lines.append(f"{cond_label}={cval}: n={n}, best={best:.4f if best is not None else 'N/A'}")
            ax.text(0.05, 0.95, "\n".join(lines), transform=ax.transAxes,
                    fontsize=8, va="top", fontfamily="monospace")

    # Hide unused axes
    for i in range(len(panels), len(axes_flat)):
        axes_flat[i].set_axis_off()

fig.suptitle("MAESTRO — Experimental Summary", fontsize=10, y=1.01)
plt.tight_layout()
""").strip()

# ── Plan builder ──────────────────────────────────────────────────────────────

def build_execution_plan_from_tool_calls(session, tool_calls: List[dict]) -> List[dict]:
    plan: List[dict] = []

    for tc in tool_calls:
        name = tc["function"]["name"]
        args: dict = {}
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            pass

        if name == "extract_and_check_feasibility":
            plan.append({
                "kind":          "extract_feasibility",
                "step_id":       str(__import__("uuid").uuid4())[:8],
                "label":         f"Extract: {args.get('case_name', 'Case Study')}",
                "case_name":     args.get("case_name", "Case Study"),
                "instrument_id": "knowledge",
                "dependencies":  [],
                "status":        "pending",
            })

        elif name == "plan_workflow":
            steps = args.get("steps", [])
            for step in steps:
                # ── Defensive defaults ────────────────────────────────────────────
                if not step.get("label"):
                    kind  = step.get("kind", "step")
                    cond  = step.get("condition_label", "")
                    val   = step.get("condition_value", "")
                    opt   = step.get("optimiser_name", "")
                    if kind == "optimise_condition" and cond:
                        opt_display = f" [{opt}]" if opt else ""
                        step["label"] = f"Optimise {cond}={val}{opt_display}"
                    elif kind == "synthesise":
                        step["label"] = "Synthesise sample"
                    elif kind == "characterise":
                        step["label"] = "Characterise sample"
                    else:
                        step["label"] = kind.replace("_", " ").title()

                if not step.get("step_id"):
                    step["step_id"] = str(__import__("uuid").uuid4())[:8]

                raw_id = step.get("instrument_id") or step.get("instrument") or step.get("kind") or "unknown"
                step["instrument_id"] = str(raw_id)
                step.setdefault("status", "pending")
                step.setdefault("dependencies", [])

                if step.get("kind") == "optimise_condition":
                    if not step.get("condition_label"):
                        step["condition_label"] = "condition"
                    if step.get("condition_value") is None:
                        step["condition_value"] = 0.0
                    else:
                        step["condition_value"] = float(step["condition_value"])
                    if not step.get("free_params"):
                        step["free_params"] = []
                    if not step.get("objective_metric"):
                        step["objective_metric"] = "objective"
                    if not step.get("n_calls"):
                        step["n_calls"] = session.optimiser_config.n_calls
                    if not step.get("n_initial_points"):
                        step["n_initial_points"] = session.optimiser_config.n_initial_points
                    if not step.get("optimiser_name"):
                        step["optimiser_name"] = session.optimiser_config.name

                plan.append(step)

        elif name == "generate_plot":
            plan.append({
                "kind":          "generate_plot",
                "step_id":       str(__import__("uuid").uuid4())[:8],
                "label":         args.get("description", "Generate figure"),
                "instrument_id": "reporting",
                "plot_code":     args.get("plot_code", ""),
                "dependencies":  [],
                "status":        "pending",
            })

        elif name == "analyse_data":
            plan.append({
                "kind":           "analyse_data",
                "step_id":        str(__import__("uuid").uuid4())[:8],
                "label":          args.get("description", "Analyse data"),
                "instrument_id":  "reporting",
                "analysis_code":  args.get("analysis_code", ""),
                "dependencies":   [],
                "status":         "pending",
            })

        elif name == "query_database":
            plan.append({
                "kind":          "query_database",
                "step_id":       str(__import__("uuid").uuid4())[:8],
                "label":         args.get("description", "Query database"),
                "instrument_id": "memory",
                "sql":           args.get("sql", ""),
                "description":   args.get("description", ""),
                "dependencies":  [],
                "status":        "pending",
            })

        elif name == "list_samples":
            plan.append({
                "kind":          "list_samples",
                "step_id":       str(__import__("uuid").uuid4())[:8],
                "label":         "List samples",
                "instrument_id": "memory",
                "dependencies":  [],
                "status":        "pending",
            })

    return plan


# ── Timeline builder ──────────────────────────────────────────────────────────

def build_dynamic_timeline(session) -> List[dict]:
    items: List[dict] = []

    if session.active_document_id:
        items.append({"label": "Paper loaded", "status": "done"})

    if session.extracted_campaign:
        c   = session.extracted_campaign
        ocs = c.operating_conditions
        if ocs:
            oc     = ocs[0]
            n_runs = len(oc.get("values", []))
            items.append({
                "label":  f"Campaign: {c.target_case_study} ({n_runs} {oc.get('name','condition')} runs)",
                "status": "done",
            })
        else:
            items.append({"label": f"Campaign: {c.target_case_study}", "status": "done"})

    if session.agent_state.awaiting_confirmation:
        items.append({"label": "Awaiting workflow approval", "status": "active"})

    if session.background_job_active:
        items.append({
            "label":  session.background_job_label or "Workflow running",
            "status": "active",
        })

    if session.sample_registry:
        # Count all successfully synthesised samples (prepared OR subsequently tested)
        n_synthesised = sum(
            1 for s in session.sample_registry
            if s.status in ("prepared", "tested")
        )
        # Count only those that have been characterised (have test results)
        n_characterised = sum(
            1 for s in session.sample_registry
            if s.status == "tested"
        )
        # Count synthesis failures separately
        n_failed = sum(
            1 for s in session.sample_registry
            if s.status == "failed"
        )
        label = f"Samples: {n_synthesised} synthesised, {n_characterised} characterised"
        if n_failed > 0:
            label += f", {n_failed} failed"
        items.append({"label": label, "status": "done"})

    if session.show_plotter_image:
        items.append({"label": "Figure generated", "status": "done"})

    if not items:
        items.append({"label": "No active workflow", "status": "pending"})

    return items