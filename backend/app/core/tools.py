"""
Physical lab agents and BO execution engine.

Phase 3: fully domain-agnostic plan builder and BO engine.
- build_execution_plan_from_tool_calls() driven entirely by CampaignSpec
- expand_optimise_condition_to_events() replaces expand_optimise_power_to_events()
- Surrogate called via general interface: condition dict + param dict
- ResultEntry created via make_result_entry() factory
- All battery-specific hardcoding removed from plan/execution layer
- Backward compat: power_W / best_energy / best_am / best_por still
  populated where applicable
"""
from __future__ import annotations

import json
import math
import tempfile
from typing import Dict, List, Optional, Tuple

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
from app.core.models import ExecutionEvent, make_result_entry
from app.core.surrogate import predict_f


# ── Failure probability model ─────────────────────────────────────────────────

def sampler_failure_probability(
    params: Dict[str, float],
) -> float:
    """
    Domain-agnostic failure probability.

    For the battery surrogate, uses active_material + porosity.
    For other domains, falls back to the base failure rate.
    This keeps the sampler realistic for battery campaigns while
    not breaking for other domains.
    """
    active_material = params.get(
        "active_material",
        params.get("am", params.get("active_material_wt", None)),
    )
    porosity = params.get(
        "porosity",
        params.get("por", params.get("electrode_porosity", None)),
    )

    if active_material is not None and porosity is not None:
        am_factor  = max(0.0, (float(active_material) - 94.5) / 1.5)
        por_factor = max(0.0, (35.0 - float(porosity)) / 5.0)
        p = SAMPLER_BASE_FAIL_PROB + 0.06 * am_factor + 0.07 * por_factor
        return float(min(0.25, max(0.0, p)))

    return float(SAMPLER_BASE_FAIL_PROB)


# ── Physical agents ───────────────────────────────────────────────────────────

class SamplerAgent:
    """
    Prepares a sample given arbitrary parameter dict.
    Returns the same dict on success, or a failure dict.
    """
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
    """
    Tests a prepared sample under a given condition dict.

    General interface: accepts arbitrary param dict + condition dict.
    Internally calls the battery surrogate if the right params are
    present; otherwise returns a placeholder value.

    Phase 3 note: in a real SDL this would call the actual instrument.
    For the virtual lab, the surrogate is the ground truth.
    """
    def test(
        self,
        material:   Dict,
        conditions: Dict[str, float],
    ) -> float:
        params = material.get("params", {})

        # ── Battery surrogate path ────────────────────────────────────────────
        # Resolve active_material
        am = (
            params.get("active_material")
            or params.get("am")
            or params.get("active_material_wt")
        )
        # Resolve porosity
        por = (
            params.get("porosity")
            or params.get("por")
            or params.get("electrode_porosity")
        )
        # Resolve power from conditions
        power = (
            conditions.get("power_W")
            or conditions.get("power")
            or conditions.get("discharge_power")
            or conditions.get("applied_power")
        )

        if am is not None and por is not None and power is not None:
            true_val = predict_f(float(am), float(por), float(power))
            return float(true_val + np.random.normal(0.0, TESTER_NOISE_SIGMA))

        # ── Generic fallback ──────────────────────────────────────────────────
        # For non-battery domains: return a synthetic value based on
        # the surrogate of the first two free params.
        # In Phase 3 this will be replaced by real instrument calls.
        param_values = list(params.values())
        if len(param_values) >= 2:
            x, y = float(param_values[0]), float(param_values[1])
            z = float(list(conditions.values())[0]) if conditions else 100.0
            true_val = predict_f(
                # Normalise to battery surrogate input range
                min(98.0, max(88.0, x)),
                min(60.0, max(20.0, y)),
                min(250.0, max(50.0, z)),
            )
            return float(true_val + np.random.normal(0.0, TESTER_NOISE_SIGMA))

        # Last resort: return a noisy constant
        return float(50.0 + np.random.normal(0.0, TESTER_NOISE_SIGMA))


sampler_agent = SamplerAgent()
tester_agent  = TesterAgent()


# ── Results store helpers ─────────────────────────────────────────────────────

def get_or_create_result_for_condition(
    results_store:   List[dict],
    condition_label: str,
    condition_value: float,
) -> dict:
    """
    Find or create a result entry for a given condition.
    Uses (condition_label, condition_value) as the composite key.
    Backward compat: also matches on power_W for existing sessions.
    """
    for r in results_store:
        # New-style match
        if (
            r.get("condition_label") == condition_label
            and abs(r.get("condition_value", float("nan")) - condition_value) < 1e-9
        ):
            return r
        # Backward-compat match for old sessions using power_W
        if (
            condition_label in ("power_W", "power")
            and "power_W" in r
            and abs(r["power_W"] - condition_value) < 1e-9
            and r.get("condition_label") is None
        ):
            # Upgrade in-place
            r["condition_label"] = condition_label
            r["condition_value"] = condition_value
            return r

    # Create new entry
    entry = make_result_entry(condition_label, condition_value)
    results_store.append(entry)
    return entry


# ── Phase 2C: resource log helper ─────────────────────────────────────────────

def _log_resource(session, tool: str, start_min: int, end_min: int):
    """Append a resource usage entry for the Gantt timeline."""
    session.resource_log.append({
        "tool":      tool,
        "day":       session.virtual_day_index,
        "start_min": start_min,
        "end_min":   end_min,
    })
    session.resource_log = session.resource_log[-200:]


# ── General BO execution engine ───────────────────────────────────────────────

def expand_optimise_condition_to_events(
    session,
    step:          dict,
    results_store: List[dict],
) -> List[ExecutionEvent]:
    """
    Run a full GP-BO loop for one operating condition value.

    Phase 3: fully domain-agnostic.
    - condition_label / condition_value replace power_W
    - free_params is a list of {name, min, max, unit} dicts
    - objective_metric is the name of the thing being maximised
    - Results stored via make_result_entry() with general fields
    - Backward compat fields (power_W, best_energy, best_am, best_por)
      still populated where applicable

    Parameters in step dict:
        condition_label:  str   e.g. "power_W", "temperature_C"
        condition_value:  float e.g. 150.0, 300.0
        free_params:      list  [{name, min, max, unit}, ...]
        objective_metric: str   e.g. "specific_energy", "CO2_conversion"
        n_calls:          int
        n_initial_points: int
    """
    condition_label  = step["condition_label"]
    condition_value  = float(step["condition_value"])
    free_params      = step["free_params"]       # [{name, min, max, unit}]
    objective_metric = step.get("objective_metric", "objective")
    n_calls          = int(step["n_calls"])
    n_init           = int(step["n_initial_points"])

    # Build condition dict for tester
    conditions = {condition_label: condition_value}

    events: List[ExecutionEvent] = []

    # ── Start event ───────────────────────────────────────────────────────────
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

    # ── Time check ────────────────────────────────────────────────────────────
    feasible = max_successes_fit_in_remaining_time(session)
    adjusted = min(n_calls, feasible)
    res      = get_or_create_result_for_condition(
        results_store, condition_label, condition_value
    )

    # Populate param_names on first creation
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

    # ── Build skopt Optimizer ─────────────────────────────────────────────────
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

    # ── BO loop ───────────────────────────────────────────────────────────────
    best_objective = res.get("best_objective")
    successes      = 0
    attempts       = 0
    failed_samples = int(res.get("failed_samples", 0))
    max_attempts   = max(adjusted, adjusted * MAX_TOTAL_ATTEMPTS_FACTOR)

    while successes < adjusted and attempts < max_attempts:

        # Time check
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
                },
            ))
            # Record outstanding task
            remaining_calls = adjusted - successes
            if remaining_calls > 0:
                session.outstanding_tasks.append({
                    "kind":              "optimise_condition",
                    "condition_label":   condition_label,
                    "condition_value":   condition_value,
                    "condition_unit":    step.get("condition_unit", ""),
                    "remaining_n_calls": remaining_calls,
                    "free_params":       free_params,
                    "objective_metric":  objective_metric,
                    # Backward compat
                    "power_W":           condition_value,
                })
            break

        # ── BO suggestion ─────────────────────────────────────────────────────
        suggestion  = opt.ask()
        param_dict  = {
            p["name"]: float(v)
            for p, v in zip(free_params, suggestion)
        }
        attempts += 1

        param_str = ", ".join(
            f"{k}={v:.3f}" for k, v in param_dict.items()
        )
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

        # ── Tester ────────────────────────────────────────────────────────────
        events.append(ExecutionEvent(
            event_type="tester_start",
            message=(
                f"Testing at {condition_label}="
                f"{condition_value} {step.get('condition_unit', '')}..."
            ),
            equipment="tester",
            category="execution",
            payload={
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

        # ── Persist to DB ─────────────────────────────────────────────────────
        # Write to DB using general fields; battery-specific fields
        # populated where available for backward compat
        am  = param_dict.get(
            "active_material",
            param_dict.get("am", 0.0)
        )
        por = param_dict.get(
            "porosity",
            param_dict.get("por", 0.0)
        )
        power = conditions.get(
            "power_W",
            conditions.get("power", condition_value)
        )
        write_evaluation(
            float(power), float(am), float(por),
            objective_value, timestamp,
        )

        # ── Update results store ──────────────────────────────────────────────
        res["X"].append(list(suggestion))
        res["y"].append(objective_value)
        res["failed_samples"] = failed_samples
        res["attempts"]       = attempts
        res["param_names"]    = [p["name"] for p in free_params]

        if best_objective is None or objective_value > best_objective:
            best_objective          = objective_value
            res["best_objective"]   = objective_value
            res["best_energy"]      = objective_value   # backward compat
            res["best_params"]      = dict(param_dict)

            # Backward compat: populate best_am / best_por if present
            if "active_material" in param_dict:
                res["best_am"]  = param_dict["active_material"]
            if "porosity" in param_dict:
                res["best_por"] = param_dict["porosity"]

        # ── Result event ──────────────────────────────────────────────────────
        events.append(ExecutionEvent(
            event_type="tester_done",
            message=(
                f"Result: {objective_value:.4f} {objective_metric} @ "
                f"{condition_label}={condition_value}"
            ),
            equipment="tester",
            category="analysis",
            payload={
                "objective_value": objective_value,
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

    # ── Completion event ──────────────────────────────────────────────────────
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


# ── Backward-compat wrapper ───────────────────────────────────────────────────

def expand_optimise_power_to_events(
    session,
    step:          dict,
    results_store: List[dict],
) -> List[ExecutionEvent]:
    """
    Backward-compatible wrapper around expand_optimise_condition_to_events.
    Translates old-style power-specific step dicts to the new general format.
    Called when the plan contains old-style "optimise_power" steps.
    """
    power_W  = float(step["power_W"])
    am_min   = float(step.get("am_min",  88.0))
    am_max   = float(step.get("am_max",  98.0))
    por_min  = float(step.get("por_min", 20.0))
    por_max  = float(step.get("por_max", 60.0))

    general_step = {
        "condition_label":  "power_W",
        "condition_value":  power_W,
        "condition_unit":   "W",
        "free_params": [
            {"name": "active_material", "min": am_min, "max": am_max, "unit": "wt%"},
            {"name": "porosity",        "min": por_min,"max": por_max,"unit": "%"},
        ],
        "objective_metric": "specific_energy",
        "n_calls":          int(step.get("n_calls", 20)),
        "n_initial_points": int(step.get("n_initial_points", 6)),
    }
    return expand_optimise_condition_to_events(session, general_step, results_store)


# ── Plotter ───────────────────────────────────────────────────────────────────

def plotter(results: List[dict], out_file: str = None) -> str:
    """
    Generate a multi-panel summary figure.

    Phase 3: domain-agnostic labels derived from result entries.
    - condition_label used for subplot titles
    - param_names used for axis labels
    - objective_metric from payload used for colorbar label
    Falls back to battery-specific labels for backward compat.
    """
    if out_file is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="maestro_plot_", delete=False
        )
        out_file = tmp.name
        tmp.close()

    n_cols   = 3
    n_total  = len(results) + 1
    n_rows   = math.ceil(n_total / n_cols)
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows)
    )
    axes = np.atleast_1d(axes).ravel()

    for i, res in enumerate(results[:len(axes) - 1]):
        ax = axes[i]

        # ── Labels ────────────────────────────────────────────────────────────
        condition_label = res.get("condition_label", "power_W")
        condition_value = res.get("condition_value", res.get("power_W", 0))
        param_names     = res.get("param_names", ["param_1", "param_2"])
        x_label         = param_names[0] if len(param_names) > 0 else "param_1"
        y_label         = param_names[1] if len(param_names) > 1 else "param_2"
        obj_label       = "Objective"

        title = f"{condition_label}={condition_value}"

        if not res["X"]:
            ax.set_title(title)
            ax.set_axis_off()
            continue

        X  = np.array(res["X"])
        y  = np.array(res["y"])
        sc = ax.scatter(
            X[:, 0], X[:, 1] if X.shape[1] > 1 else np.zeros(len(X)),
            c=y, cmap="plasma", s=40,
        )

        # Best point marker
        best_params = res.get("best_params", {})
        best_x = best_params.get(x_label)
        best_y = best_params.get(y_label)

        # Fallback to legacy fields
        if best_x is None:
            best_x = res.get("best_am")
        if best_y is None:
            best_y = res.get("best_por")

        if best_x is not None and best_y is not None:
            ax.scatter(
                [best_x], [best_y],
                facecolors="none", edgecolors="black",
                s=120, linewidths=1.5, label="Best",
            )
            ax.legend(fontsize=7)

        ax.set_title(title, fontsize=9)
        ax.set_xlabel(x_label, fontsize=8)
        ax.set_ylabel(y_label, fontsize=8)
        fig.colorbar(sc, ax=ax).set_label(obj_label, fontsize=7)

    # Hide unused axes
    for ax in axes[len(results):-1]:
        ax.set_visible(False)

    # ── Optimal parameter path ────────────────────────────────────────────────
    ax_path = axes[-1]
    valid   = [
        r for r in results
        if r.get("best_params") or r.get("best_am") is not None
    ]

    if valid:
        # Sort by condition value
        valid.sort(key=lambda r: r.get("condition_value", r.get("power_W", 0)))

        condition_values = [
            r.get("condition_value", r.get("power_W", 0)) for r in valid
        ]
        condition_label = valid[0].get("condition_label", "power_W")
        param_names     = valid[0].get("param_names", ["param_1", "param_2"])
        x_label         = param_names[0] if len(param_names) > 0 else "param_1"
        y_label         = param_names[1] if len(param_names) > 1 else "param_2"

        xs, ys, objs = [], [], []
        for r in valid:
            bp = r.get("best_params", {})
            x  = bp.get(x_label, r.get("best_am"))
            y  = bp.get(y_label, r.get("best_por"))
            o  = r.get("best_objective", r.get("best_energy", 0))
            if x is not None and y is not None:
                xs.append(float(x))
                ys.append(float(y))
                objs.append(float(o) if o is not None else 0.0)

        if xs:
            ax_path.plot(xs, ys, "-k", lw=1.5, alpha=0.6)
            sc2 = ax_path.scatter(
                xs, ys, c=objs, cmap="viridis", s=60, edgecolors="black"
            )
            for x, y, cv in zip(xs, ys, condition_values):
                ax_path.text(
                    x + 0.02 * (max(xs) - min(xs) + 1e-9),
                    y,
                    f"{cv}",
                    fontsize=7,
                )
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

def execute_plan_step(session, step: dict, query_database_fn) -> Dict:
    """
    Execute one step of the approved workflow plan.

    Phase 3: handles both new-style "optimise_condition" steps and
    old-style "optimise_power" steps for backward compatibility.
    """
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
        from app.core.skills import describe_extracted_campaign

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
                    "I need a paper to be uploaded before I can check "
                    "feasibility. Please attach a PDF using the 📎 button."
                ),
            })
            return {"status": "error", "message": "No document uploaded"}

        try:
            extraction = extract_case_study_to_campaign(
                session.active_document_id, case_name
            )
            session.extracted_campaign = extraction.campaign

            # Update active_condition_key from extracted campaign
            ocs = extraction.campaign.operating_conditions
            if ocs:
                session.active_condition_key = ocs[0].get("name", "power_W")

            feasibility = extraction.campaign.capability_match
            is_feasible = feasibility.get("feasible", False)

            session.live_event_queue.append(ExecutionEvent(
                event_type="feasibility_result",
                message=(
                    f"Feasibility: "
                    f"{'✅ Feasible' if is_feasible else '⚠️ Partial/Not feasible'}"
                ),
                equipment="knowledge",
                category="knowledge",
            ))

            # ── Feasibility report ────────────────────────────────────────────
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
                    f"- `{p['name']}` "
                    f"({p.get('min')}–{p.get('max')} {p.get('unit', '')}) "
                    f"{'✅' if ok else '❌ not available in current lab'}"
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
                    f"✅ **Fully reproducible** with the current virtual lab.\n"
                    f"This will run **{n_runs} separate BO campaigns**.\n"
                    f"Say **'run it'** or **'execute the campaign'** to proceed."
                )
            else:
                lines.append(
                    f"⚠️ **Partially feasible.** "
                    f"Missing: {missing_p + missing_o}. "
                    f"Add the required tools in the Lab Builder."
                )

            # Reference figures
            if extraction.campaign.source_document_id:
                from app.core.documents import get_document
                try:
                    doc = get_document(extraction.campaign.source_document_id)
                    for s in doc.sections:
                        if case_name.lower() in s.heading.lower():
                            figs = get_figures_for_section(
                                extraction.campaign.source_document_id,
                                s.heading,
                            )
                            if figs:
                                lines.append("\n### Reference Figures")
                                for fig in figs[:3]:
                                    lines.append(
                                        f"![{fig.caption}]"
                                        f"(/api{fig.served_url})"
                                    )
                            break
                except Exception:
                    pass

            if extraction.campaign.assumptions:
                lines.append("\n### Assumptions")
                for a in extraction.campaign.assumptions:
                    lines.append(f"- {a}")

            session.agent_state.messages.append({
                "role":    "assistant",
                "content": "\n".join(lines),
            })
            return {"status": "ok", "feasible": is_feasible}

        except Exception as e:
            session.agent_state.messages.append({
                "role":    "assistant",
                "content": (
                    f"I encountered an error extracting the campaign: `{e}`"
                ),
            })
            return {"status": "error", "message": str(e)}

    # ── General condition BO (Phase 3) ────────────────────────────────────────
    if kind == "optimise_condition":
        events = expand_optimise_condition_to_events(
            session, step, results_store
        )
        session.live_event_queue.extend(events)
        return {"status": "ok"}

    # ── Legacy power BO (backward compat) ─────────────────────────────────────
    if kind == "optimise_power":
        events = expand_optimise_power_to_events(
            session, step, results_store
        )
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

    Phase 3: fully driven by CampaignSpec structure.
    - Iterates over ANY operating conditions, not just power_W
    - Uses ANY free parameters from parameter_space
    - Handles single condition dimension with multiple values
    - Backward compat: falls back gracefully if campaign uses old structure

    IMPORTANT: extract_and_check_feasibility is NOT added to the
    background job plan — it runs synchronously in confirm_pending().
    Only experiment execution steps go into the background job.
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
            # Runs synchronously — NOT in background job
            pass

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
                    "message":   (
                        "No campaign extracted yet. "
                        "Please extract a campaign first."
                    ),
                    "equipment": "knowledge",
                    "category":  "knowledge",
                })
                continue

            c = session.extracted_campaign

            # ── Resolve free parameters ───────────────────────────────────────
            # Build a lookup by name (case-insensitive)
            param_lookup = {
                p["name"].lower(): p
                for p in c.parameter_space
            }

            # ── Resolve operating conditions ──────────────────────────────────
            operating_conditions = c.operating_conditions

            if not operating_conditions:
                # No operating conditions extracted — this shouldn't happen
                # after our extraction fix, but handle gracefully:
                # Run a single BO campaign with no fixed condition
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

            # ── One BO campaign per condition value ───────────────────────────
            # Update session's active condition key
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

        elif name == "plotter":
            plan.append({"kind": "plotter"})

        elif name == "query_database":
            plan.append({
                "kind":        "query_database",
                "sql":         args.get("sql", ""),
                "description": args.get("description", ""),
            })

    return plan


def _resolve_free_params(
    param_lookup: Dict[str, dict],
) -> List[dict]:
    """
    Build the free_params list for a BO step from the campaign's
    parameter_space lookup dict.

    Returns a list of {name, min, max, unit} dicts with sensible
    defaults if bounds are missing.
    """
    free_params = []
    for name, p in param_lookup.items():
        p_min = p.get("min")
        p_max = p.get("max")

        # Skip params with no bounds — can't run BO without them
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
    """Build the campaign progress timeline for the right panel."""
    items: List[dict] = []

    if session.active_document_id:
        items.append({"label": "Paper uploaded", "status": "done"})

    if session.extracted_campaign:
        c = session.extracted_campaign
        # Show condition summary
        ocs = c.operating_conditions
        if ocs:
            oc      = ocs[0]
            n_runs  = len(oc.get("values", []))
            oc_name = oc.get("name", "condition")
            items.append({
                "label":  (
                    f"Campaign: {c.target_case_study} "
                    f"({n_runs} {oc_name} runs)"
                ),
                "status": "done",
            })
        else:
            items.append({
                "label":  f"Campaign: {c.target_case_study}",
                "status": "done",
            })

    if session.agent_state.awaiting_confirmation:
        items.append({
            "label":  "Awaiting workflow approval",
            "status": "active",
        })

    if session.background_job_active:
        items.append({
            "label":  session.background_job_label or "Workflow running",
            "status": "active",
        })

    for t in session.outstanding_tasks[:3]:
        cond_label = t.get("condition_label", "condition")
        cond_value = t.get("condition_value", t.get("power_W", "?"))
        items.append({
            "label": (
                f"Pending: {cond_label}={cond_value} "
                f"({int(t['remaining_n_calls'])} evals)"
            ),
            "status": "pending",
        })

    if session.show_plotter_image:
        items.append({"label": "Summary figure generated", "status": "done"})

    if not items:
        items.append({
            "label":  "Waiting for scientific task",
            "status": "pending",
        })

    return items