"""
Physical lab agents and BO execution engine.

Phase 3:
- Domain-agnostic plan builder driven by WorkflowPlan/WorkflowStep
- Sample registry: prepare_sample_step, test_sample_step, list_samples_step
- DAG step resolution: {{variable}} references between steps
- Backward compat: optimise_power still works
"""
from __future__ import annotations

import json
import math
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from skopt import Optimizer
from skopt.space import Real

from app.core.config import (
    MAX_TOTAL_ATTEMPTS_FACTOR,
    SAMPLER_BASE_FAIL_PROB,
    TESTER_NOISE_SIGMA,
    VIRTUAL_MIN_SAMPLER,
    VIRTUAL_MIN_TESTER,
)
from app.core.database import write_evaluation
from app.core.lab import (
    add_virtual_time,
    format_virtual_time,
    lab_minutes_remaining,
    max_successes_fit_in_remaining_time,
)
from app.core.models import (
    ExecutionEvent,
    Sample,
    SampleResult,
    WorkflowPlan,
    WorkflowStep,
    generate_sample_id,
    make_result_entry,
)
from app.core.surrogate import predict_f


# ── Failure probability model ─────────────────────────────────────────────────

def sampler_failure_probability(params: Dict[str, float]) -> float:
    active_material = (
        params.get("active_material")
        or params.get("am")
        or params.get("active_material_wt")
    )
    porosity = (
        params.get("porosity")
        or params.get("por")
        or params.get("electrode_porosity")
    )
    if active_material is not None and porosity is not None:
        am_factor  = max(0.0, (float(active_material) - 94.5) / 1.5)
        por_factor = max(0.0, (35.0 - float(porosity)) / 5.0)
        p = SAMPLER_BASE_FAIL_PROB + 0.06 * am_factor + 0.07 * por_factor
        return float(min(0.25, max(0.0, p)))
    return float(SAMPLER_BASE_FAIL_PROB)


# ── Physical agents ───────────────────────────────────────────────────────────

class SamplerAgent:
    def sample(self, params: Dict[str, float]) -> Dict:
        fail_prob = sampler_failure_probability(params)
        if np.random.rand() < fail_prob:
            return {
                "status":              "failed",
                "reason":              "Sample preparation defect",
                "failure_probability": fail_prob,
            }
        return {
            "status":              "ok",
            "params":              params,
            "failure_probability": fail_prob,
        }


class TesterAgent:
    def test(
        self,
        material:   Dict,
        conditions: Dict[str, float],
    ) -> float:
        params = material.get("params", {})

        am = (
            params.get("active_material")
            or params.get("am")
            or params.get("active_material_wt")
        )
        por = (
            params.get("porosity")
            or params.get("por")
            or params.get("electrode_porosity")
        )
        power = (
            conditions.get("power_W")
            or conditions.get("power")
            or conditions.get("discharge_power")
            or conditions.get("applied_power")
        )

        if am is not None and por is not None and power is not None:
            true_val = predict_f(float(am), float(por), float(power))
            return float(true_val + np.random.normal(0.0, TESTER_NOISE_SIGMA))

        param_values = list(params.values())
        if len(param_values) >= 2:
            x, y = float(param_values[0]), float(param_values[1])
            z = float(list(conditions.values())[0]) if conditions else 100.0
            true_val = predict_f(
                min(98.0, max(88.0, x)),
                min(60.0, max(20.0, y)),
                min(250.0, max(50.0, z)),
            )
            return float(true_val + np.random.normal(0.0, TESTER_NOISE_SIGMA))

        return float(50.0 + np.random.normal(0.0, TESTER_NOISE_SIGMA))


sampler_agent = SamplerAgent()
tester_agent  = TesterAgent()


# ── Results store helpers ─────────────────────────────────────────────────────

def get_or_create_result_for_condition(
    results_store:   List[dict],
    condition_label: str,
    condition_value: float,
) -> dict:
    for r in results_store:
        if (
            r.get("condition_label") == condition_label
            and abs(r.get("condition_value", float("nan")) - condition_value) < 1e-9
        ):
            return r
        if (
            condition_label in ("power_W", "power")
            and "power_W" in r
            and abs(r["power_W"] - condition_value) < 1e-9
            and r.get("condition_label") is None
        ):
            r["condition_label"] = condition_label
            r["condition_value"] = condition_value
            return r

    entry = make_result_entry(condition_label, condition_value)
    results_store.append(entry)
    return entry


# ── Phase 2C: resource log ────────────────────────────────────────────────────

def _log_resource(session, tool: str, start_min: int, end_min: int):
    session.resource_log.append({
        "tool":      tool,
        "day":       session.virtual_day_index,
        "start_min": start_min,
        "end_min":   end_min,
    })
    session.resource_log = session.resource_log[-200:]


# ── DAG variable resolution ───────────────────────────────────────────────────

def _resolve_ref(value: Any, context: Dict[str, Any]) -> Any:
    """
    Resolve {{variable}} references in step fields.
    e.g. "{{sample_id}}" → "S-1-001"
    """
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\{\{(\w+)\}\}")
    match   = pattern.fullmatch(value.strip())
    if match:
        var_name = match.group(1)
        return context.get(var_name, value)
    return value


# ── Sample Registry operations ────────────────────────────────────────────────

def prepare_sample_step(
    session,
    step:    dict,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a prepare_sample step.

    Runs SamplerAgent with the given params.
    On success: creates a Sample in session.sample_registry,
                stores sample_id in context for downstream steps.
    On failure: creates a failed Sample, raises so plan can handle.

    Domain-agnostic: params dict can contain any parameter names.
    """
    params      = step.get("params", {})
    instrument  = step.get("instrument", "SamplerAgent")
    produces    = step.get("produces", "sample_id")

    session.live_event_queue.append(ExecutionEvent(
        event_type="sampler_start",
        message=(
            f"Preparing sample: "
            + ", ".join(f"{k}={v}" for k, v in params.items())
        ),
        equipment="sampler",
        category="execution",
        payload={"params": params},
    ))

    t_before = session.virtual_clock_minutes
    add_virtual_time(session, VIRTUAL_MIN_SAMPLER)
    _log_resource(session, "sampler", t_before, session.virtual_clock_minutes)

    result = sampler_agent.sample(params)

    sample_id = generate_sample_id(session)
    timestamp = format_virtual_time(session.virtual_clock_minutes)

    if result["status"] != "ok":
        # Create failed sample in registry
        failed_sample = Sample(
            sample_id=sample_id,
            params=params,
            prepared_by=instrument,
            status="failed",
            prepared_at=timestamp,
            prepared_day=session.virtual_day_index,
            failure_reason=result.get("reason", "Unknown failure"),
        )
        session.sample_registry.append(failed_sample)

        session.live_event_queue.append(ExecutionEvent(
            event_type="sampler_fail",
            message=(
                f"Sample {sample_id} failed: {result.get('reason', 'defect')} "
                f"(p={result['failure_probability']:.0%})"
            ),
            equipment="sampler",
            category="execution",
            payload={"sample_id": sample_id, "params": params},
        ))
        return {
            "status":    "failed",
            "sample_id": sample_id,
            "reason":    result.get("reason"),
        }

    # Create successful sample in registry
    new_sample = Sample(
        sample_id=sample_id,
        params=params,
        prepared_by=instrument,
        status="prepared",
        prepared_at=timestamp,
        prepared_day=session.virtual_day_index,
    )
    session.sample_registry.append(new_sample)

    # Store in DAG context for downstream steps
    context[produces] = sample_id

    session.live_event_queue.append(ExecutionEvent(
        event_type="sampler_done",
        message=(
            f"Sample {sample_id} prepared successfully. "
            f"Stored in lab inventory."
        ),
        equipment="sampler",
        category="execution",
        payload={
            "sample_id": sample_id,
            "params":    params,
            "status":    "prepared",
        },
    ))

    # Append to agent messages so user can see the sample ID
    session.agent_state.messages.append({
        "role":    "assistant",
        "content": (
            f"✅ **Sample prepared:** `{sample_id}`\n\n"
            f"| Parameter | Value |\n"
            f"|-----------|-------|\n"
            + "\n".join(
                f"| {k} | {v} |"
                for k, v in params.items()
            )
            + f"\n\nSample is stored in the lab inventory. "
            f"You can test it at any time by saying "
            f"'test sample {sample_id} at [condition]'."
        ),
    })

    return {
        "status":    "ok",
        "sample_id": sample_id,
        "params":    params,
    }


def test_sample_step(
    session,
    step:    dict,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a test_sample step.

    Looks up sample from registry by sample_id (or {{sample_id}} ref).
    Runs TesterAgent under given conditions.
    Appends SampleResult to sample.results.

    Domain-agnostic: conditions and outputs are arbitrary dicts.
    """
    # Resolve sample_id — may be a DAG reference
    sample_ref = _resolve_ref(step.get("sample_ref", ""), context)
    conditions = step.get("conditions", {})
    measures   = step.get("measures", "objective")
    instrument = step.get("instrument", "TesterAgent")

    # Find sample in registry
    sample = next(
        (s for s in session.sample_registry if s.sample_id == sample_ref),
        None,
    )

    if sample is None:
        session.live_event_queue.append(ExecutionEvent(
            event_type="tester_fail",
            message=f"Sample {sample_ref} not found in registry.",
            equipment="tester",
            category="execution",
            payload={"sample_ref": sample_ref},
        ))
        return {"status": "error", "message": f"Sample {sample_ref} not found"}

    if sample.status == "failed":
        return {
            "status":  "error",
            "message": f"Sample {sample_ref} failed preparation — cannot test",
        }

    session.live_event_queue.append(ExecutionEvent(
        event_type="tester_start",
        message=(
            f"Testing sample {sample_ref}: "
            + ", ".join(f"{k}={v}" for k, v in conditions.items())
        ),
        equipment="tester",
        category="execution",
        payload={"sample_id": sample_ref, "conditions": conditions},
    ))

    t_before = session.virtual_clock_minutes
    add_virtual_time(session, VIRTUAL_MIN_TESTER)
    _log_resource(session, "tester", t_before, session.virtual_clock_minutes)

    material = {"params": sample.params}
    value    = tester_agent.test(material, conditions)

    timestamp = format_virtual_time(session.virtual_clock_minutes)

    # Create SampleResult
    result = SampleResult(
        tested_by=instrument,
        conditions=conditions,
        outputs={measures: value},
        tested_at=timestamp,
        tested_day=session.virtual_day_index,
    )
    sample.results.append(result)
    sample.status = "tested"

    # Write to DB for SQL queryability
    am    = sample.params.get("active_material", sample.params.get("am", 0.0))
    por   = sample.params.get("porosity", sample.params.get("por", 0.0))
    power = conditions.get("power_W", conditions.get("power", 0.0))
    write_evaluation(float(power), float(am), float(por), value, timestamp)

    session.live_event_queue.append(ExecutionEvent(
        event_type="tester_done",
        message=(
            f"Sample {sample_ref}: {measures} = {value:.4f} "
            f"@ {', '.join(f'{k}={v}' for k, v in conditions.items())}"
        ),
        equipment="tester",
        category="analysis",
        payload={
            "sample_id":  sample_ref,
            "conditions": conditions,
            "outputs":    {measures: value},
        },
    ))
    session.live_event_queue.append(ExecutionEvent(
        event_type="memory_update",
        message="Recording result to experimental database.",
        equipment="memory",
        category="analysis",
        payload={},
    ))

    # Append result to agent messages
    session.agent_state.messages.append({
        "role":    "assistant",
        "content": (
            f"⚡ **Test result for `{sample_ref}`:**\n\n"
            f"| | |\n|---|---|\n"
            + "\n".join(
                f"| {k} | {v} |"
                for k, v in conditions.items()
            )
            + "\n"
            + "\n".join(
                f"| **{k}** | **{v:.4f}** |"
                for k, v in {measures: value}.items()
            )
        ),
    })

    return {
        "status":     "ok",
        "sample_id":  sample_ref,
        "conditions": conditions,
        "outputs":    {measures: value},
    }


def list_samples_step(session) -> Dict[str, Any]:
    """Return a summary of all samples in the registry."""
    samples = session.sample_registry
    if not samples:
        session.agent_state.messages.append({
            "role":    "assistant",
            "content": "No samples in the lab inventory yet.",
        })
        return {"status": "ok", "count": 0, "samples": []}

    lines = [
        f"## Lab Sample Inventory ({len(samples)} samples)\n",
        "| Sample ID | Parameters | Status | Prepared | Results |",
        "|-----------|------------|--------|----------|---------|",
    ]
    for s in samples:
        params_str  = ", ".join(f"{k}={v}" for k, v in s.params.items())
        results_str = f"{len(s.results)} test(s)" if s.results else "untested"
        lines.append(
            f"| `{s.sample_id}` | {params_str} | {s.status} | "
            f"Day {s.prepared_day} {s.prepared_at} | {results_str} |"
        )

    session.agent_state.messages.append({
        "role":    "assistant",
        "content": "\n".join(lines),
    })

    return {
        "status":  "ok",
        "count":   len(samples),
        "samples": [s.model_dump() for s in samples],
    }


# ── General BO execution engine ───────────────────────────────────────────────

def expand_optimise_condition_to_events(
    session,
    step:          dict,
    results_store: List[dict],
) -> List[ExecutionEvent]:
    """
    Run a full GP-BO loop for one operating condition value.
    Phase 3: fully domain-agnostic.
    """
    condition_label  = step["condition_label"]
    condition_value  = float(step["condition_value"])
    free_params      = step["free_params"]
    objective_metric = step.get("objective_metric", "objective")
    n_calls          = int(step["n_calls"])
    n_init           = int(step["n_initial_points"])
    conditions       = {condition_label: condition_value}

    events: List[ExecutionEvent] = []

    param_summary = ", ".join(
        f"{p['name']} [{p['min']}–{p['max']} {p.get('unit','')}]"
        for p in free_params
    )
    events.append(ExecutionEvent(
        event_type="optimiser_start",
        message=(
            f"Starting BO campaign: {condition_label}="
            f"{condition_value} {step.get('condition_unit', '')} | "
            f"Optimising: {param_summary} | "
            f"Objective: {objective_metric}"
        ),
        equipment="optimiser",
        category="planning",
        payload={
            "condition_label": condition_label,
            "condition_value": condition_value,
        },
    ))

    feasible = max_successes_fit_in_remaining_time(session)
    adjusted = min(n_calls, feasible)
    res      = get_or_create_result_for_condition(
        results_store, condition_label, condition_value
    )

    if not res.get("param_names"):
        res["param_names"] = [p["name"] for p in free_params]

    if adjusted <= 0:
        events.append(ExecutionEvent(
            event_type="optimiser_skip",
            message=(
                f"Insufficient lab time for "
                f"{condition_label}={condition_value} "
                f"({lab_minutes_remaining(session)} min remaining). Skipping."
            ),
            equipment="optimiser",
            category="planning",
            payload={
                "condition_label": condition_label,
                "condition_value": condition_value,
            },
        ))
        return events

    dimensions = [
        Real(float(p["min"]), float(p["max"]), name=p["name"])
        for p in free_params
    ]
    opt = Optimizer(
        dimensions=dimensions,
        base_estimator="GP",
        n_initial_points=min(n_init, adjusted),
        acq_func="EI",
        random_state=42,
    )

    best_objective = res.get("best_objective")
    successes      = 0
    attempts       = 0
    failed_samples = int(res.get("failed_samples", 0))
    max_attempts   = max(adjusted, adjusted * MAX_TOTAL_ATTEMPTS_FACTOR)

    while successes < adjusted and attempts < max_attempts:
        remaining = lab_minutes_remaining(session)
        if remaining < (VIRTUAL_MIN_SAMPLER + VIRTUAL_MIN_TESTER):
            events.append(ExecutionEvent(
                event_type="optimiser_pause",
                message=(
                    f"Lab time exhausted — stopping at "
                    f"{condition_label}={condition_value} "
                    f"with {successes}/{adjusted} evaluations completed."
                ),
                equipment="optimiser",
                category="planning",
                payload={
                    "condition_label": condition_label,
                    "condition_value": condition_value,
                    "completed":       successes,
                    "requested":       adjusted,
                },
            ))
            remaining_calls = adjusted - successes
            if remaining_calls > 0:
                session.outstanding_tasks.append({
                    "kind":              "optimise_condition",
                    "condition_label":   condition_label,
                    "condition_value":   condition_value,
                    "condition_unit":    step.get("condition_unit", ""),
                    "remaining_n_calls": remaining_calls,
                    "completed_calls":   successes,
                    "free_params":       free_params,
                    "objective_metric":  objective_metric,
                    "power_W":           condition_value,
                })
            break

        suggestion = opt.ask()
        param_dict = {
            p["name"]: float(v)
            for p, v in zip(free_params, suggestion)
        }
        attempts += 1

        param_str = ", ".join(f"{k}={v:.3f}" for k, v in param_dict.items())
        events.append(ExecutionEvent(
            event_type="candidate_proposed",
            message=(
                f"BO proposes: {param_str} @ "
                f"{condition_label}={condition_value}"
            ),
            equipment="optimiser",
            category="planning",
            payload={
                "params":          param_dict,
                "condition_label": condition_label,
                "condition_value": condition_value,
            },
        ))

        # ── Sampler ───────────────────────────────────────────────────────────
        events.append(ExecutionEvent(
            event_type="sampler_start",
            message=f"Preparing sample: {param_str}",
            equipment="sampler",
            category="execution",
            payload={"params": param_dict},
        ))
        t_before = session.virtual_clock_minutes
        add_virtual_time(session, VIRTUAL_MIN_SAMPLER)
        _log_resource(session, "sampler", t_before, session.virtual_clock_minutes)

        material = sampler_agent.sample(param_dict)

        if material["status"] != "ok":
            failed_samples += 1

            # Register failed sample in registry
            failed_id        = generate_sample_id(session)
            failed_timestamp = format_virtual_time(session.virtual_clock_minutes)
            session.sample_registry.append(Sample(
                sample_id=failed_id,
                params=param_dict,
                prepared_by="SamplerAgent",
                status="failed",
                prepared_at=failed_timestamp,
                prepared_day=session.virtual_day_index,
                failure_reason="Electrode preparation defect",
                notes=(
                    f"BO iteration attempt @ "
                    f"{condition_label}={condition_value}"
                ),
            ))

            events.append(ExecutionEvent(
                event_type="sampler_fail",
                message=(
                    f"Sample failed "
                    f"(p={material['failure_probability']:.0%}). Retrying."
                ),
                equipment="sampler",
                category="execution",
                payload={"params": param_dict},
            ))
            continue

        # ── Register successful sample in registry ────────────────────────────
        # Every prepared sample — whether from BO or ad-hoc — is registered.
        # This gives the user a full inventory of all lab work done.
        bo_sample_id  = generate_sample_id(session)
        bo_timestamp  = format_virtual_time(session.virtual_clock_minutes)
        bo_sample     = Sample(
            sample_id=bo_sample_id,
            params=param_dict,
            prepared_by="SamplerAgent",
            status="prepared",
            prepared_at=bo_timestamp,
            prepared_day=session.virtual_day_index,
            notes=(
                f"BO iteration {successes + 1} @ "
                f"{condition_label}={condition_value}"
            ),
        )
        session.sample_registry.append(bo_sample)

        # ── Tester ────────────────────────────────────────────────────────────
        events.append(ExecutionEvent(
            event_type="tester_start",
            message=(
                f"Testing {bo_sample_id} at {condition_label}="
                f"{condition_value} {step.get('condition_unit', '')}..."
            ),
            equipment="tester",
            category="execution",
            payload={
                "sample_id":       bo_sample_id,
                "condition_label": condition_label,
                "condition_value": condition_value,
            },
        ))
        t_before = session.virtual_clock_minutes
        add_virtual_time(session, VIRTUAL_MIN_TESTER)
        _log_resource(session, "tester", t_before, session.virtual_clock_minutes)

        objective_value = tester_agent.test(material, conditions)
        opt.tell(suggestion, -objective_value)
        successes += 1

        timestamp = format_virtual_time(session.virtual_clock_minutes)

        # ── Update sample registry with test result ───────────────────────────
        bo_sample.status = "tested"
        bo_sample.results.append(SampleResult(
            tested_by="TesterAgent",
            conditions=dict(conditions),
            outputs={objective_metric: objective_value},
            tested_at=timestamp,
            tested_day=session.virtual_day_index,
        ))

        # ── Persist to DB ─────────────────────────────────────────────────────
        am    = param_dict.get("active_material", param_dict.get("am", 0.0))
        por   = param_dict.get("porosity", param_dict.get("por", 0.0))
        power = conditions.get("power_W", conditions.get("power", condition_value))
        write_evaluation(float(power), float(am), float(por), objective_value, timestamp)

        # ── Update results store ──────────────────────────────────────────────
        res["X"].append(list(suggestion))
        res["y"].append(objective_value)
        res["failed_samples"] = failed_samples
        res["attempts"]       = attempts
        res["param_names"]    = [p["name"] for p in free_params]

        if best_objective is None or objective_value > best_objective:
            best_objective        = objective_value
            res["best_objective"] = objective_value
            res["best_energy"]    = objective_value
            res["best_params"]    = dict(param_dict)
            if "active_material" in param_dict:
                res["best_am"]  = param_dict["active_material"]
            if "porosity" in param_dict:
                res["best_por"] = param_dict["porosity"]

        events.append(ExecutionEvent(
            event_type="tester_done",
            message=(
                f"Result: {objective_value:.4f} {objective_metric} @ "
                f"{condition_label}={condition_value}"
            ),
            equipment="tester",
            category="analysis",
            payload={
                "objective_value":  objective_value,
                "objective_metric": objective_metric,
                "params":           param_dict,
                "condition_label":  condition_label,
                "condition_value":  condition_value,
            },
        ))
        events.append(ExecutionEvent(
            event_type="memory_update",
            message="Recording result to experimental database.",
            equipment="memory",
            category="analysis",
            payload={},
        ))

    best_str = f"{best_objective:.4f}" if best_objective is not None else "N/A"
    events.append(ExecutionEvent(
        event_type="optimiser_complete",
        message=(
            f"BO complete: {condition_label}={condition_value}. "
            f"Best {objective_metric}: {best_str}"
        ),
        equipment="optimiser",
        category="planning",
        payload={
            "condition_label":  condition_label,
            "condition_value":  condition_value,
            "best_objective":   best_objective,
            "objective_metric": objective_metric,
        },
    ))
    return events


def expand_optimise_power_to_events(
    session, step: dict, results_store: List[dict]
) -> List[ExecutionEvent]:
    """Backward-compat wrapper."""
    power_W = float(step["power_W"])
    general_step = {
        "condition_label":  "power_W",
        "condition_value":  power_W,
        "condition_unit":   "W",
        "free_params": [
            {"name": "active_material", "min": float(step.get("am_min", 88.0)),  "max": float(step.get("am_max", 98.0)),  "unit": "wt%"},
            {"name": "porosity",        "min": float(step.get("por_min", 20.0)), "max": float(step.get("por_max", 60.0)), "unit": "%"},
        ],
        "objective_metric": "specific_energy",
        "n_calls":          int(step.get("n_calls", 20)),
        "n_initial_points": int(step.get("n_initial_points", 6)),
    }
    return expand_optimise_condition_to_events(session, general_step, results_store)


# ── Plotter ───────────────────────────────────────────────────────────────────

def plotter(results: List[dict], out_file: str = None) -> str:
    if out_file is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="maestro_plot_", delete=False
        )
        out_file = tmp.name
        tmp.close()

    n_cols    = 3
    n_total   = len(results) + 1
    n_rows    = math.ceil(n_total / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
    axes      = np.atleast_1d(axes).ravel()

    for i, res in enumerate(results[:len(axes) - 1]):
        ax = axes[i]
        condition_label = res.get("condition_label", "power_W")
        condition_value = res.get("condition_value", res.get("power_W", 0))
        param_names     = res.get("param_names", ["param_1", "param_2"])
        x_label         = param_names[0] if len(param_names) > 0 else "param_1"
        y_label         = param_names[1] if len(param_names) > 1 else "param_2"
        title           = f"{condition_label}={condition_value}"

        if not res["X"]:
            ax.set_title(title); ax.set_axis_off(); continue

        X  = np.array(res["X"])
        y  = np.array(res["y"])
        sc = ax.scatter(
            X[:, 0],
            X[:, 1] if X.shape[1] > 1 else np.zeros(len(X)),
            c=y, cmap="plasma", s=40,
        )
        bp    = res.get("best_params", {})
        best_x = bp.get(x_label, res.get("best_am"))
        best_y = bp.get(y_label, res.get("best_por"))
        if best_x is not None and best_y is not None:
            ax.scatter([best_x], [best_y], facecolors="none", edgecolors="black", s=120, linewidths=1.5, label="Best")
            ax.legend(fontsize=7)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel(x_label, fontsize=8)
        ax.set_ylabel(y_label, fontsize=8)
        fig.colorbar(sc, ax=ax).set_label("Objective", fontsize=7)

    for ax in axes[len(results):-1]:
        ax.set_visible(False)

    ax_path = axes[-1]
    valid   = [r for r in results if r.get("best_params") or r.get("best_am") is not None]
    if valid:
        valid.sort(key=lambda r: r.get("condition_value", r.get("power_W", 0)))
        param_names = valid[0].get("param_names", ["param_1", "param_2"])
        x_label     = param_names[0] if len(param_names) > 0 else "param_1"
        y_label     = param_names[1] if len(param_names) > 1 else "param_2"
        xs, ys, objs, cvs = [], [], [], []
        for r in valid:
            bp  = r.get("best_params", {})
            x   = bp.get(x_label, r.get("best_am"))
            y   = bp.get(y_label, r.get("best_por"))
            o   = r.get("best_objective", r.get("best_energy", 0))
            cv  = r.get("condition_value", r.get("power_W", 0))
            if x is not None and y is not None:
                xs.append(float(x)); ys.append(float(y))
                objs.append(float(o) if o else 0.0); cvs.append(cv)
        if xs:
            ax_path.plot(xs, ys, "-k", lw=1.5, alpha=0.6)
            sc2 = ax_path.scatter(xs, ys, c=objs, cmap="viridis", s=60, edgecolors="black")
            for x, y, cv in zip(xs, ys, cvs):
                ax_path.text(x + 0.02 * (max(xs) - min(xs) + 1e-9), y, f"{cv}", fontsize=7)
            ax_path.set_title("Optimal parameter path", fontsize=9)
            ax_path.set_xlabel(x_label, fontsize=8)
            ax_path.set_ylabel(y_label, fontsize=8)
            fig.colorbar(sc2, ax=ax_path).set_label("Best Objective", fontsize=7)
    else:
        ax_path.set_title("Optimal parameter path")
        ax_path.text(0.5, 0.5, "No results yet", ha="center", va="center")
        ax_path.set_axis_off()

    plt.tight_layout()
    plt.savefig(out_file, dpi=150)
    plt.close(fig)
    return out_file


# ── Plan execution ────────────────────────────────────────────────────────────

def execute_plan_step(
    session,
    step:              dict,
    query_database_fn,
    dag_context:       Optional[Dict[str, Any]] = None,
) -> Dict:
    """
    Execute one step of the approved workflow plan.

    Phase 3: handles WorkflowStep kinds including prepare_sample,
    test_sample, list_samples, optimise_condition, and legacy kinds.

    dag_context: shared dict for passing outputs between steps
                 e.g. step 1 sets context["sample_id"] = "S-1-001"
                      step 2 reads context["sample_id"]
    """
    if dag_context is None:
        dag_context = {}

    results_store = session.agent_state.results_store
    kind          = step["kind"]

    # ── Narration ─────────────────────────────────────────────────────────────
    if kind == "narration":
        session.live_event_queue.append(ExecutionEvent(
            event_type="narration",
            message=step["message"],
            equipment=step.get("equipment"),
            category=step.get("category", "knowledge"),
        ))
        return {"status": "ok"}

    # ── Feasibility extraction ────────────────────────────────────────────────
    if kind == "extract_feasibility":
        from app.core.extraction import extract_case_study_to_campaign
        case_name = step.get("case_name", "Case Study")

        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_read",
            message=f"Reading paper to extract '{case_name}'...",
            equipment="knowledge",
            category="knowledge",
        ))

        if not session.active_document_id:
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": (
                    "I need a paper to be uploaded before I can check feasibility."
                ),
            })
            return {"status": "error", "message": "No document uploaded"}

        try:
            extraction = extract_case_study_to_campaign(
                session.active_document_id, case_name
            )
            session.extracted_campaign = extraction.campaign
            ocs = extraction.campaign.operating_conditions
            if ocs:
                session.active_condition_key = ocs[0].get("name", "power_W")

            feasibility = extraction.campaign.capability_match
            is_feasible = feasibility.get("feasible", False)

            session.live_event_queue.append(ExecutionEvent(
                event_type="feasibility_result",
                message=f"Feasibility: {'✅ Feasible' if is_feasible else '⚠️ Partial'}",
                equipment="knowledge",
                category="knowledge",
            ))

            missing_p = feasibility.get("missing_params", [])
            missing_o = feasibility.get("missing_outputs", [])

            lines = [
                f"## Feasibility Report: {case_name}\n",
                f"**Campaign:** {extraction.campaign.title}",
                f"**Objective:** `{extraction.campaign.objective_metric}`\n",
                "### Free Parameters (BO search space)",
            ]
            for p in extraction.campaign.parameter_space:
                ok = p["name"] not in missing_p
                lines.append(
                    f"- `{p['name']}` ({p.get('min')}–{p.get('max')} {p.get('unit', '')}) "
                    f"{'✅' if ok else '❌ not available'}"
                )
            if extraction.campaign.operating_conditions:
                lines.append("\n### Operating Conditions (separate runs)")
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
                n_runs = sum(
                    len(oc.get("values", []))
                    for oc in extraction.campaign.operating_conditions
                ) or 1
                lines.append(
                    f"✅ **Fully reproducible.** "
                    f"This will run **{n_runs} separate BO campaigns**.\n"
                    f"Say **'run it'** to proceed."
                )
            else:
                lines.append(
                    f"⚠️ **Partially feasible.** "
                    f"Missing: {missing_p + missing_o}."
                )

            if extraction.campaign.assumptions:
                lines.append("\n### Assumptions")
                for a in extraction.campaign.assumptions:
                    lines.append(f"- {a}")

            session.agent_state.messages.append({
                "role": "assistant", "content": "\n".join(lines),
            })
            return {"status": "ok", "feasible": is_feasible}

        except Exception as e:
            session.agent_state.messages.append({
                "role": "assistant",
                "content": f"Error extracting campaign: `{e}`",
            })
            return {"status": "error", "message": str(e)}

    # ── Prepare sample (Phase 3) ──────────────────────────────────────────────
    if kind == "prepare_sample":
        return prepare_sample_step(session, step, dag_context)

    # ── Test sample (Phase 3) ─────────────────────────────────────────────────
    if kind == "test_sample":
        return test_sample_step(session, step, dag_context)

    # ── List samples (Phase 3) ────────────────────────────────────────────────
    if kind == "list_samples":
        return list_samples_step(session)

    # ── General condition BO ──────────────────────────────────────────────────
    if kind == "optimise_condition":
        events = expand_optimise_condition_to_events(session, step, results_store)
        session.live_event_queue.extend(events)
        return {"status": "ok"}

    # ── Legacy power BO ───────────────────────────────────────────────────────
    if kind == "optimise_power":
        events = expand_optimise_power_to_events(session, step, results_store)
        session.live_event_queue.extend(events)
        return {"status": "ok"}

    # ── Plotter ───────────────────────────────────────────────────────────────
    if kind == "plotter":
        session.live_event_queue.append(ExecutionEvent(
            event_type="plotter_start",
            message="Generating summary figure...",
            equipment="reporting",
            category="reporting",
        ))
        fig_path = plotter(results_store)
        session.show_plotter_image = fig_path
        session.live_event_queue.append(ExecutionEvent(
            event_type="plotter_done",
            message="Summary figure ready.",
            equipment="reporting",
            category="reporting",
        ))
        return {"status": "ok", "figure_path": fig_path}

    # ── Database query ────────────────────────────────────────────────────────
    if kind == "query_database":
        session.live_event_queue.append(ExecutionEvent(
            event_type="memory_query",
            message="Querying experimental database...",
            equipment="memory",
            category="analysis",
        ))
        result = query_database_fn(step.get("sql", ""))
        result["query_description"] = step.get("description", "")
        return result

    return {"status": "error", "message": f"Unknown step kind: {kind}"}


# ── General plan builder ──────────────────────────────────────────────────────

def build_execution_plan_from_tool_calls(
    session, tool_calls: List[dict]
) -> List[dict]:
    """
    Convert LLM tool calls into a concrete execution plan.

    Phase 3: handles plan_workflow, prepare_sample, test_sample,
    list_samples in addition to existing tool calls.
    """
    plan: List[dict] = []

    for tc in tool_calls:
        name = tc["function"]["name"]
        args: dict = {}
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            pass

        if name == "extract_and_check_feasibility":
            pass  # runs synchronously in confirm_pending

        elif name == "plan_workflow":
            # The LLM has proposed a structured plan
            # Convert WorkflowStep dicts directly to plan steps
            steps = args.get("steps", [])
            for step in steps:
                plan.append(step)

        elif name == "run_extracted_campaign":
            plan.append({
                "kind":      "narration",
                "message":   "Formulating execution plan from extracted campaign...",
                "equipment": "knowledge",
                "category":  "knowledge",
            })
            if session.extracted_campaign is None:
                plan.append({
                    "kind":      "narration",
                    "message":   "No campaign extracted yet.",
                    "equipment": "knowledge",
                    "category":  "knowledge",
                })
                continue

            c          = session.extracted_campaign
            param_lookup = {p["name"].lower(): p for p in c.parameter_space}

            operating_conditions = c.operating_conditions
            if not operating_conditions:
                plan.append({
                    "kind":             "optimise_condition",
                    "condition_label":  "run",
                    "condition_value":  1.0,
                    "condition_unit":   "",
                    "free_params":      _resolve_free_params(param_lookup),
                    "objective_metric": c.objective_metric or "objective",
                    "n_calls":          20,
                    "n_initial_points": 6,
                })
                continue

            primary_oc = operating_conditions[0]
            session.active_condition_key = primary_oc.get("name", "power_W")

            for oc in operating_conditions:
                oc_name   = oc.get("name", "condition")
                oc_unit   = oc.get("unit", "")
                oc_values = oc.get("values", [])
                if not oc_values:
                    continue
                for value in oc_values:
                    plan.append({
                        "kind":             "optimise_condition",
                        "condition_label":  oc_name,
                        "condition_value":  float(value),
                        "condition_unit":   oc_unit,
                        "free_params":      _resolve_free_params(param_lookup),
                        "objective_metric": c.objective_metric or "objective",
                        "n_calls":          20,
                        "n_initial_points": 6,
                    })

        elif name == "prepare_sample":
            plan.append({
                "kind":       "prepare_sample",
                "label":      f"Prepare sample: {args.get('params', {})}",
                "instrument": args.get("instrument", "SamplerAgent"),
                "params":     args.get("params", {}),
                "produces":   args.get("produces", "sample_id"),
            })

        elif name == "test_sample":
            plan.append({
                "kind":       "test_sample",
                "label":      f"Test sample {args.get('sample_id', '?')}",
                "instrument": args.get("instrument", "TesterAgent"),
                "sample_ref": args.get("sample_id", "{{sample_id}}"),
                "conditions": args.get("conditions", {}),
                "measures":   args.get("measures", "specific_energy"),
            })

        elif name == "list_samples":
            plan.append({"kind": "list_samples"})

        elif name == "plotter":
            plan.append({"kind": "plotter"})

        elif name == "query_database":
            plan.append({
                "kind":        "query_database",
                "sql":         args.get("sql", ""),
                "description": args.get("description", ""),
            })

    return plan


def _resolve_free_params(param_lookup: Dict[str, dict]) -> List[dict]:
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


# ── Timeline builder ──────────────────────────────────────────────────────────

def build_dynamic_timeline(session) -> List[dict]:
    items: List[dict] = []

    if session.active_document_id:
        items.append({"label": "Paper uploaded", "status": "done"})

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

    for t in session.outstanding_tasks[:3]:
        cond_label = t.get("condition_label", "condition")
        cond_value = t.get("condition_value", t.get("power_W", "?"))
        completed  = t.get("completed_calls", 0)
        remaining  = t.get("remaining_n_calls", 0)
        items.append({
            "label":  f"Incomplete: {cond_label}={cond_value} ({completed} done, {remaining} remaining)",
            "status": "pending",
        })

    if session.sample_registry:
        n_prepared = sum(1 for s in session.sample_registry if s.status == "prepared")
        n_tested   = sum(1 for s in session.sample_registry if s.status == "tested")
        items.append({
            "label":  f"Samples: {n_prepared} prepared, {n_tested} tested",
            "status": "done",
        })

    if session.show_plotter_image:
        items.append({"label": "Summary figure generated", "status": "done"})

    if not items:
        items.append({"label": "Waiting for scientific task", "status": "pending"})

    return items