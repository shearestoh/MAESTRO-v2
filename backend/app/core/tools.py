"""
Physical lab agents and BO execution engine.
Phase 2C: resource_log updated for Gantt timeline display.
"""
from __future__ import annotations

import json
import math
import tempfile
from typing import Dict, List

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
from app.core.models import ExecutionEvent
from app.core.surrogate import predict_f


# ── Failure probability model ─────────────────────────────────────────────────

def sampler_failure_probability(active_material: float, porosity: float) -> float:
    am_factor  = max(0.0, (active_material - 94.5) / 1.5)
    por_factor = max(0.0, (35.0 - porosity) / 5.0)
    p = SAMPLER_BASE_FAIL_PROB + 0.06 * am_factor + 0.07 * por_factor
    return float(min(0.25, max(0.0, p)))


# ── Physical agents ───────────────────────────────────────────────────────────

class SamplerAgent:
    def sample(self, active_material: float, porosity: float) -> Dict:
        fail_prob = sampler_failure_probability(active_material, porosity)
        if np.random.rand() < fail_prob:
            return {
                "status":      "failed",
                "reason":      "Electrode preparation defect",
                "failure_probability": fail_prob,
            }
        return {
            "status":            "ok",
            "active_material":   active_material,
            "porosity":          porosity,
            "failure_probability": fail_prob,
        }


class TesterAgent:
    def test(self, material: Dict, power_W: float) -> float:
        true_val = predict_f(
            material["active_material"], material["porosity"], power_W
        )
        return float(true_val + np.random.normal(0.0, TESTER_NOISE_SIGMA))


sampler_agent = SamplerAgent()
tester_agent  = TesterAgent()


# ── Results store helpers ─────────────────────────────────────────────────────

def get_or_create_result_for_power(
    results_store: List[dict], power_W: float
) -> dict:
    for r in results_store:
        if abs(r["power_W"] - power_W) < 1e-9:
            return r
    new_entry = {
        "power_W":            power_W,
        "X":                  [],
        "y":                  [],
        "best_am":            None,
        "best_por":           None,
        "best_energy":        None,
        "failed_samples":     0,
        "attempts":           0,
        "termination_reason": None,
    }
    results_store.append(new_entry)
    return new_entry


# ── Phase 2C: resource log helper ─────────────────────────────────────────────

def _log_resource(session, tool: str, start_min: int, end_min: int):
    """
    Append a resource usage entry for the Gantt timeline.
    tool: "sampler" | "tester" | "memory" | "optimiser"
    """
    session.resource_log.append({
        "tool":      tool,
        "day":       session.virtual_day_index,
        "start_min": start_min,
        "end_min":   end_min,
    })
    # Keep last 200 entries
    session.resource_log = session.resource_log[-200:]


# ── BO execution engine ───────────────────────────────────────────────────────

def expand_optimise_power_to_events(
    session, step: dict, results_store: List[dict]
) -> List[ExecutionEvent]:
    """
    Run a full GP-BO loop for one operating condition (power level).
    Returns a list of ExecutionEvents queued for WebSocket streaming.
    """
    power_W = float(step["power_W"])
    n_calls = int(step["n_calls"])
    n_init  = int(step["n_initial_points"])
    am_min, am_max   = float(step["am_min"]),  float(step["am_max"])
    por_min, por_max = float(step["por_min"]), float(step["por_max"])

    events: List[ExecutionEvent] = []

    events.append(ExecutionEvent(
        event_type="optimiser_start",
        message=f"Starting BO campaign at {int(power_W)} W — objective: specific energy",
        equipment="optimiser",
        category="planning",
        payload={"power_W": power_W},
    ))

    feasible = max_successes_fit_in_remaining_time(session)
    adjusted = min(n_calls, feasible)
    res      = get_or_create_result_for_power(results_store, power_W)

    if adjusted <= 0:
        events.append(ExecutionEvent(
            event_type="optimiser_skip",
            message=(
                f"Insufficient lab time for {int(power_W)} W "
                f"({lab_minutes_remaining(session)} min remaining). Skipping."
            ),
            equipment="optimiser",
            category="planning",
            payload={"power_W": power_W},
        ))
        return events

    opt = Optimizer(
        dimensions=[
            Real(am_min, am_max, name="active_material"),
            Real(por_min, por_max, name="porosity"),
        ],
        base_estimator="GP",
        n_initial_points=min(n_init, adjusted),
        acq_func="EI",
        random_state=42,
    )

    best_energy    = res["best_energy"]
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
                    f"Lab time exhausted — stopping at {int(power_W)} W "
                    f"with {successes}/{adjusted} evaluations completed."
                ),
                equipment="optimiser",
                category="planning",
                payload={"power_W": power_W, "completed": successes},
            ))
            # Record outstanding task
            remaining_calls = adjusted - successes
            if remaining_calls > 0:
                session.outstanding_tasks.append({
                    "kind":              "optimise_power",
                    "power_W":           power_W,
                    "remaining_n_calls": remaining_calls,
                    "params": {
                        "n_initial_points": n_init,
                        "am_min": am_min, "am_max": am_max,
                        "por_min": por_min, "por_max": por_max,
                    },
                })
            break

        suggestion = opt.ask()
        am, por    = float(suggestion[0]), float(suggestion[1])
        attempts  += 1

        events.append(ExecutionEvent(
            event_type="candidate_proposed",
            message=f"BO proposes: {list(res['X'][0])[0] if res['X'] else 'param_1'}={am:.2f}, param_2={por:.2f} @ {int(power_W)} W",
            equipment="optimiser",
            category="planning",
            payload={"active_material": am, "porosity": por, "power_W": power_W},
        ))

        # Sampler
        events.append(ExecutionEvent(
            event_type="sampler_start",
            message=f"Preparing sample: param_1={am:.2f}, param_2={por:.2f}",
            equipment="sampler",
            category="execution",
            payload={"active_material": am, "porosity": por},
        ))
        t_before = session.virtual_clock_minutes
        add_virtual_time(session, VIRTUAL_MIN_SAMPLER)
        _log_resource(session, "sampler", t_before, session.virtual_clock_minutes)

        material = sampler_agent.sample(am, por)

        if material["status"] != "ok":
            failed_samples += 1
            events.append(ExecutionEvent(
                event_type="sampler_fail",
                message=f"Sample failed (p={material['failure_probability']:.0%}). Retrying.",
                equipment="sampler",
                category="execution",
                payload={"active_material": am, "porosity": por},
            ))
            continue

        # Tester
        events.append(ExecutionEvent(
            event_type="tester_start",
            message=f"Testing at {int(power_W)} W...",
            equipment="tester",
            category="execution",
            payload={"power_W": power_W},
        ))
        t_before = session.virtual_clock_minutes
        add_virtual_time(session, VIRTUAL_MIN_TESTER)
        _log_resource(session, "tester", t_before, session.virtual_clock_minutes)

        energy = tester_agent.test(material, power_W)
        opt.tell(suggestion, -energy)
        successes += 1

        timestamp = format_virtual_time(session.virtual_clock_minutes)
        write_evaluation(power_W, am, por, energy, timestamp)

        res["X"].append([am, por])
        res["y"].append(energy)
        res["failed_samples"] = failed_samples
        res["attempts"]       = attempts

        if best_energy is None or energy > best_energy:
            best_energy      = energy
            res["best_energy"] = energy
            res["best_am"]     = am
            res["best_por"]    = por

        events.append(ExecutionEvent(
            event_type="tester_done",
            message=f"Result: {energy:.2f} (objective units) @ {int(power_W)} W",
            equipment="tester",
            category="analysis",
            payload={
                "energy":          energy,
                "power_W":         power_W,
                "active_material": am,
                "porosity":        por,
            },
        ))
        events.append(ExecutionEvent(
            event_type="memory_update",
            message="Recording result to experimental database.",
            equipment="memory",
            category="analysis",
            payload={},
        ))

    events.append(ExecutionEvent(
        event_type="optimiser_complete",
        message=(
            f"BO complete at {int(power_W)} W. "
            f"Best: {best_energy:.2f}" if best_energy else
            f"BO complete at {int(power_W)} W."
        ),
        equipment="optimiser",
        category="planning",
        payload={"power_W": power_W, "best_energy": best_energy},
    ))
    return events


# ── Plotter ───────────────────────────────────────────────────────────────────

def plotter(results: List[dict], out_file: str = None) -> str:
    if out_file is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="maestro_plot_", delete=False
        )
        out_file = tmp.name
        tmp.close()

    n_cols   = 3
    n_total  = len(results) + 1
    n_rows   = math.ceil(n_total / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
    axes     = np.atleast_1d(axes).ravel()

    for i, res in enumerate(results[:len(axes) - 1]):
        ax = axes[i]
        if not res["X"]:
            ax.set_title(f"Condition {res['power_W']:.0f}")
            ax.set_axis_off()
            continue
        X  = np.array(res["X"])
        y  = np.array(res["y"])
        sc = ax.scatter(X[:, 0], X[:, 1], c=y, cmap="plasma", s=40)
        if res["best_am"] is not None:
            ax.scatter(
                [res["best_am"]], [res["best_por"]],
                facecolors="none", edgecolors="black",
                s=120, linewidths=1.5, label="Best",
            )
            ax.legend()
        ax.set_title(f"Condition {res['power_W']:.0f}")
        ax.set_xlabel("Parameter 1")
        ax.set_ylabel("Parameter 2")
        fig.colorbar(sc, ax=ax).set_label("Objective")

    for ax in axes[len(results):-1]:
        ax.set_visible(False)

    ax_path = axes[-1]
    valid   = [r for r in results if r["best_am"] is not None]
    if valid:
        idx = np.argsort([r["power_W"] for r in valid])
        am  = np.array([r["best_am"]     for r in valid])[idx]
        por = np.array([r["best_por"]    for r in valid])[idx]
        E   = np.array([r["best_energy"] for r in valid])[idx]
        P   = np.array([r["power_W"]     for r in valid])[idx]
        ax_path.plot(am, por, "-k", lw=1.5, alpha=0.6)
        sc2 = ax_path.scatter(am, por, c=E, cmap="viridis", s=60, edgecolors="black")
        for a, p, pw in zip(am, por, P):
            ax_path.text(a + 0.05, p, f"{int(pw)}", fontsize=8)
        ax_path.set_title("Optimal parameter path")
        ax_path.set_xlabel("Parameter 1")
        ax_path.set_ylabel("Parameter 2")
        fig.colorbar(sc2, ax=ax_path).set_label("Best Objective")
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
    """Execute one step of the approved workflow plan."""
    results_store = session.agent_state.results_store
    kind          = step["kind"]

    if kind == "narration":
        session.live_event_queue.append(ExecutionEvent(
            event_type="narration",
            message=step["message"],
            equipment=step.get("equipment"),
            category=step.get("category", "knowledge"),
        ))
        return {"status": "ok"}

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
                    "I need a paper to be uploaded before I can check feasibility. "
                    "Please attach a PDF using the 📎 button."
                ),
            })
            return {"status": "error", "message": "No document uploaded"}

        try:
            extraction = extract_case_study_to_campaign(
                session.active_document_id, case_name
            )
            session.extracted_campaign = extraction.campaign

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

            # Build feasibility report
            missing_p = feasibility.get("missing_params", [])
            missing_o = feasibility.get("missing_outputs", [])

            lines = [
                f"## Feasibility Report: {case_name}\n",
                f"**Campaign:** {extraction.campaign.title}",
                f"**Objective:** `{extraction.campaign.objective_metric}`\n",
                "### Parameters",
            ]
            for p in extraction.campaign.parameter_space:
                ok = p["name"] not in missing_p
                lines.append(
                    f"- `{p['name']}` "
                    f"({p.get('min')}–{p.get('max')} {p.get('unit', '')}) "
                    f"{'✅' if ok else '❌ not available in current lab'}"
                )

            lines += [
                f"\n### Output",
                f"- `{extraction.campaign.objective_metric}` "
                f"{'✅ measurable' if not missing_o else '❌ not measurable'}",
                f"\n### Verdict",
            ]

            if is_feasible:
                lines.append(
                    "✅ **Fully reproducible** with the current virtual lab.\n"
                    "Say **'run it'** or **'execute the campaign'** to proceed."
                )
            else:
                lines.append(
                    f"⚠️ **Partially feasible.** "
                    f"Missing: {missing_p + missing_o}. "
                    f"Add the required tools in the Lab Builder."
                )

            # Show reference figures if available
            from app.core.documents import get_figures_for_section
            doc_sections = extraction.evidence_snippets
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
                                        f"![{fig.caption}](/api{fig.served_url})"
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
                "content": f"I encountered an error extracting the campaign: `{e}`",
            })
            return {"status": "error", "message": str(e)}

    if kind == "optimise_power":
        events = expand_optimise_power_to_events(session, step, results_store)
        session.live_event_queue.extend(events)
        return {"status": "ok"}

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


# ── Plan builder ──────────────────────────────────────────────────────────────

def build_execution_plan_from_tool_calls(
    session, tool_calls: List[dict]
) -> List[dict]:
    """
    Convert LLM tool calls into a concrete execution plan.

    IMPORTANT: extract_and_check_feasibility is NOT added to the background
    job plan — it runs synchronously in confirm_pending() instead.
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
            # This runs synchronously — NOT in the background job
            # Handled directly in confirm_pending() before job starts
            # Do NOT add to plan
            pass

        elif name == "run_extracted_campaign":
            plan.append({
                "kind":      "narration",
                "message":   "Formulating execution plan from extracted campaign...",
                "equipment": "knowledge",
                "category":  "knowledge",
            })
            if session.extracted_campaign is not None:
                c  = session.extracted_campaign
                ps = {p["name"]: p for p in c.parameter_space}

                for oc in c.operating_conditions:
                    if oc.get("name") == "power_W":
                        for power in oc.get("values", []):
                            am  = ps.get("active_material", {})
                            por = ps.get("porosity", {})
                            plan.append({
                                "kind":             "optimise_power",
                                "power_W":          float(power),
                                "n_calls":          20,
                                "n_initial_points": 6,
                                "am_min":  float(am.get("min",  92.0)),
                                "am_max":  float(am.get("max",  96.0)),
                                "por_min": float(por.get("min", 30.0)),
                                "por_max": float(por.get("max", 50.0)),
                            })
            else:
                plan.append({
                    "kind":      "narration",
                    "message":   "No campaign extracted yet. Please extract a campaign first.",
                    "equipment": "knowledge",
                    "category":  "knowledge",
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

# ── Timeline builder ──────────────────────────────────────────────────────────

def build_dynamic_timeline(session) -> List[dict]:
    """Build the campaign progress timeline for the right panel."""
    items: List[dict] = []

    if session.active_document_id:
        items.append({"label": "Paper uploaded", "status": "done"})
    if session.extracted_campaign:
        items.append({
            "label":  f"Campaign: {session.extracted_campaign.target_case_study}",
            "status": "done",
        })
    if session.agent_state.awaiting_confirmation:
        items.append({"label": "Awaiting workflow approval", "status": "active"})
    if session.background_job_active:
        items.append({
            "label":  session.background_job_label or "Workflow running",
            "status": "active",
        })
    for t in session.outstanding_tasks[:3]:
        items.append({
            "label": (
                f"Pending: condition {int(t['power_W'])} "
                f"({int(t['remaining_n_calls'])} evals)"
            ),
            "status": "pending",
        })
    if session.show_plotter_image:
        items.append({"label": "Summary figure generated", "status": "done"})
    if not items:
        items.append({"label": "Waiting for scientific task", "status": "pending"})

    return items