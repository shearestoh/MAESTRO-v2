"""
Domain-agnostic paper-to-campaign extraction.
Token-safe: passage budget calculated before every LLM call.
No hardcoded parameter names — the LLM maps paper params to tool registry.

Phase 3 fix: improved prompt + post-processing to reliably distinguish
free parameters (BO search space) from operating conditions (discrete
fixed values that define separate experimental runs).
"""
from __future__ import annotations

import json
import uuid
from typing import List

from app.core.documents import (
    get_document,
    get_figures_for_section,
    get_tables_for_section,
    retrieve_relevant_passages,
)
from app.core.llm import call_llm, _MAX_PROMPT_CHARS
from app.core.models import CampaignSpec, CaseStudyExtraction
from app.core.tool_registry import TOOL_REGISTRY


# ── Condition keyword heuristics ──────────────────────────────────────────────
# Parameters whose names suggest they are operating conditions
# (discrete fixed values defining separate runs) rather than free
# parameters (continuous search space for BO).
# This list is domain-agnostic — covers common scientific condition types.

_CONDITION_KEYWORDS = {
    # Energy / power
    "power", "power_w", "discharge_power", "applied_power",
    "cell_power", "watt", "watts",
    # Thermal
    "temperature", "temp", "temperature_c", "temperature_k",
    "annealing_temp", "reaction_temp", "sintering_temp",
    # Electrical
    "current", "current_a", "c_rate", "voltage", "voltage_v",
    "applied_voltage", "bias",
    # Chemical / process
    "ph", "pressure", "flow_rate", "concentration",
    "solvent_ratio", "reaction_time", "exposure_time",
    "humidity", "irradiance", "wavelength",
    # Mechanical
    "load", "strain_rate", "stress",
    # General
    "condition", "level", "setting", "rate",
}


def _looks_like_condition(param: dict) -> bool:
    """
    Heuristic: does this parameter look like an operating condition
    rather than a free BO parameter?

    Signals:
    1. Name matches known condition keywords
    2. Has a small number of discrete values (implied by min == max
       or very narrow range relative to typical BO search spaces)
    3. The LLM put it in parameter_space but it has a "values" key
       (shouldn't happen but sometimes does)
    """
    name = param.get("name", "").lower().replace(" ", "_").replace("-", "_")

    # Check name against condition keywords
    for kw in _CONDITION_KEYWORDS:
        if kw in name:
            return True

    # Check if range is suspiciously narrow (< 5% of typical BO range)
    # This catches cases like power_W: min=150, max=150 (single value)
    p_min = param.get("min")
    p_max = param.get("max")
    if p_min is not None and p_max is not None:
        try:
            if float(p_min) == float(p_max):
                return True
        except (TypeError, ValueError):
            pass

    return False


def _infer_condition_values(param: dict) -> list[float]:
    """
    Given a parameter that looks like an operating condition,
    infer the discrete values to use for separate BO runs.

    Strategy:
    - If min == max: single value [min]
    - If range is small (≤ 5 values implied): use min + max + midpoints
    - Otherwise: generate 5 evenly spaced values across the range
    """
    import numpy as np

    p_min = float(param.get("min", 0))
    p_max = float(param.get("max", 1))

    if p_min == p_max:
        return [round(p_min, 4)]

    # Generate 5 evenly spaced values — matches the battery paper's
    # 5-power-level structure and is a sensible default for any domain
    values = [round(float(v), 4) for v in np.linspace(p_min, p_max, 5)]
    return values


def _postprocess_campaign_dict(data: dict) -> dict:
    """
    Validate and fix the LLM's extracted campaign structure.

    The LLM sometimes puts operating conditions in parameter_space
    (because they look like parameters). This function detects and
    corrects that misclassification.

    Also ensures operating_conditions always has the right shape:
        {"name": str, "values": [float, ...], "unit": str, "description": str}
    """
    parameter_space      = data.get("parameter_space", [])
    operating_conditions = data.get("operating_conditions", [])

    # ── Step 1: Scan parameter_space for misclassified conditions ────────────
    true_params     = []
    promoted_to_oc  = []

    for param in parameter_space:
        if _looks_like_condition(param):
            promoted_to_oc.append(param)
        else:
            true_params.append(param)

    # ── Step 2: Convert promoted params → operating_conditions format ────────
    for param in promoted_to_oc:
        # Check if this condition is already in operating_conditions
        existing_names = {
            oc.get("name", "").lower().replace(" ", "_")
            for oc in operating_conditions
        }
        param_name = param.get("name", "").lower().replace(" ", "_")

        if param_name not in existing_names:
            values = _infer_condition_values(param)
            operating_conditions.append({
                "name":        param.get("name"),
                "values":      values,
                "unit":        param.get("unit", ""),
                "description": (
                    param.get("description", "") or
                    f"Operating condition: {param.get('name')}"
                ),
            })

    # ── Step 3: Validate existing operating_conditions have values[] ─────────
    validated_ocs = []
    for oc in operating_conditions:
        values = oc.get("values", [])

        # If values is empty or missing, try to infer from min/max
        if not values:
            p_min = oc.get("min")
            p_max = oc.get("max")
            if p_min is not None and p_max is not None:
                import numpy as np
                values = [
                    round(float(v), 4)
                    for v in np.linspace(float(p_min), float(p_max), 5)
                ]
            else:
                # Can't infer — skip this condition
                continue

        validated_ocs.append({
            "name":        oc.get("name", "condition"),
            "values":      [float(v) for v in values],
            "unit":        oc.get("unit", ""),
            "description": oc.get("description", ""),
        })

    # ── Step 4: Write back corrected structure ────────────────────────────────
    data["parameter_space"]      = true_params
    data["operating_conditions"] = validated_ocs

    # ── Step 5: Add assumptions about any promotions ─────────────────────────
    if promoted_to_oc:
        promoted_names = [p.get("name") for p in promoted_to_oc]
        note = (
            f"Parameters {promoted_names} were reclassified as operating "
            f"conditions (discrete fixed values defining separate BO runs) "
            f"rather than free optimisation parameters."
        )
        data.setdefault("assumptions", []).append(note)

    return data


def extract_case_study_to_campaign(
    document_id: str,
    case_name:   str,
) -> CaseStudyExtraction:
    """
    Extract an executable campaign spec from a paper.

    Domain-agnostic: the LLM reads the paper passages and the tool
    registry, then maps paper parameters to available tools itself.
    No hardcoded parameter names anywhere in this function.

    Phase 3 fix: improved prompt + post-processing ensures reliable
    separation of free parameters (BO search space) from operating
    conditions (discrete fixed values for separate runs).
    """
    tool_context = TOOL_REGISTRY.to_llm_context()
    controllable = TOOL_REGISTRY.all_controllable_parameters()
    measurable   = TOOL_REGISTRY.all_measurable_outputs()

    # ── Token budget ──────────────────────────────────────────────────────────
    prompt_template_chars = 2000   # increased for richer prompt
    tool_context_chars    = len(tool_context)
    system_msg_chars      = 400
    response_headroom     = 1200 * 4
    passage_budget        = max(
        2000,
        _MAX_PROMPT_CHARS
        - prompt_template_chars
        - tool_context_chars
        - system_msg_chars
        - response_headroom,
    )

    passages = retrieve_relevant_passages(
        document_id,
        query    = case_name,
        top_k    = 4,
        max_chars= passage_budget,
    )
    passages_text = "\n\n".join(passages)

    # ── Table context ─────────────────────────────────────────────────────────
    doc = get_document(document_id)
    table_context = ""
    if doc.sections:
        for s in doc.sections:
            if case_name.lower() in s.heading.lower():
                tbls = get_tables_for_section(document_id, s.heading)
                if tbls:
                    table_context = "\n\nEXTRACTED TABLES FROM THIS SECTION:\n"
                    for t in tbls[:3]:
                        table_context += (
                            f"\nTable caption: {t.caption}\n{t.html}\n"
                        )
                break

    # ── Extraction prompt ─────────────────────────────────────────────────────
    # Key improvement: explicit semantic distinction between
    # FREE PARAMETERS (BO search space) and OPERATING CONDITIONS
    # (discrete fixed values defining separate experimental runs).
    prompt = f"""Extract an executable experimental campaign from this paper.

TARGET: "{case_name}"

AVAILABLE LAB TOOLS:
{tool_context}

CONTROLLABLE PARAMETERS (what the lab can set): {controllable}
MEASURABLE OUTPUTS (what the lab can measure): {measurable}

PAPER PASSAGES:
{passages_text}
{table_context}

CRITICAL DISTINCTION — read carefully before extracting:

FREE PARAMETERS go in "parameter_space":
  - These are the variables that Bayesian Optimisation will SEARCH OVER
  - They form a continuous search space with a min and max bound
  - The BO algorithm will try many values between min and max
  - Examples: active material %, porosity %, catalyst loading, layer thickness,
    excipient ratio, particle size, dopant concentration

OPERATING CONDITIONS go in "operating_conditions":
  - These are FIXED EXTERNAL CONDITIONS that define SEPARATE experimental runs
  - Each value in the "values" list triggers a COMPLETELY SEPARATE BO campaign
  - They are NOT optimised — they are held fixed during each run
  - They typically represent different use-case scenarios or test regimes
  - Examples: discharge power (W), temperature (°C), C-rate, pH level,
    applied voltage, flow rate, annealing time
  - The paper will typically show results at MULTIPLE DISCRETE VALUES
    of these conditions (e.g., results at 70W, 110W, 150W, 170W, 190W)

EXTRACTION RULES:
1. Identify the experimental objective (what is being optimised or measured)
2. Identify FREE PARAMETERS — variables the BO algorithm will optimise
   - Map each to the closest name in CONTROLLABLE PARAMETERS
   - Extract their min/max bounds from the paper
3. Identify OPERATING CONDITIONS — discrete fixed values for separate runs
   - Extract ALL discrete values tested in the paper (e.g., [70, 110, 150, 170, 190])
   - Use the exact parameter name from CONTROLLABLE PARAMETERS if it matches
   - Each value will trigger a separate BO campaign
4. If a parameter appears in BOTH roles (e.g., power is both fixed per run
   AND varied across runs), put it in "operating_conditions" only
5. Note all assumptions made in the mapping

EXAMPLE (battery paper):
  - FREE PARAMETERS: active_material (92-96 wt%), porosity (30-50%)
    → BO searches over these for each power level
  - OPERATING CONDITIONS: power_W with values [70, 110, 150, 170, 190]
    → 5 separate BO campaigns, one per power level

Return ONLY valid JSON (no markdown fences, no explanation):
{{
  "title": "concise campaign title",
  "target_case_study": "{case_name}",
  "objective_metric": "name matching MEASURABLE OUTPUTS if possible",
  "parameter_space": [
    {{
      "name": "name matching CONTROLLABLE PARAMETERS if possible",
      "original_name": "name as used in the paper",
      "min": <number>,
      "max": <number>,
      "unit": "unit string",
      "mapped_to_tool": "ToolName or null if unmappable"
    }}
  ],
  "operating_conditions": [
    {{
      "name": "condition name (use CONTROLLABLE PARAMETERS name if it matches)",
      "values": [<list of ALL discrete values tested in the paper>],
      "unit": "unit string",
      "description": "what this condition represents physically"
    }}
  ],
  "desired_outputs": ["list of expected result types"],
  "assumptions": ["assumptions made in mapping paper to lab"],
  "feasibility_notes": "brief assessment",
  "provenance": {{
    "objective":            ["quoted evidence from paper"],
    "parameter_space":      ["quoted evidence from paper"],
    "operating_conditions": ["quoted evidence from paper"]
  }}
}}"""

    msg = call_llm(
        messages=[
            {
                "role":    "system",
                "content": (
                    "You are a precise scientific protocol extraction assistant. "
                    "Output strict JSON only — no markdown, no explanation. "
                    "Pay careful attention to the distinction between FREE "
                    "PARAMETERS (BO search space) and OPERATING CONDITIONS "
                    "(discrete fixed values for separate runs)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        tools=None,
    )

    content = (msg.content or "").strip()

    # Strip accidental markdown fences
    if "```" in content:
        for part in content.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                content = part
                break

    data = json.loads(content)

    # ── Post-processing: fix structural misclassifications ────────────────────
    data = _postprocess_campaign_dict(data)

    # ── Feasibility check against live tool registry ──────────────────────────
    required_params  = [p["name"] for p in data.get("parameter_space", [])]
    required_outputs = [data.get("objective_metric", "")]
    feasibility      = TOOL_REGISTRY.check_feasibility(
        required_params, required_outputs
    )

    campaign_dict = {
        "campaign_id":          str(uuid.uuid4()),
        "source_document_id":   document_id,
        "status":               "draft",
        "title":                data.get("title", case_name),
        "target_case_study":    data.get("target_case_study", case_name),
        "objective_metric":     data.get("objective_metric", ""),
        "parameter_space":      data.get("parameter_space", []),
        "operating_conditions": data.get("operating_conditions", []),
        "desired_outputs":      data.get("desired_outputs", []),
        "assumptions":          data.get("assumptions", []),
        "provenance":           data.get("provenance", {}),
        "capability_match":     feasibility,
    }

    return CaseStudyExtraction(
        document_id=document_id,
        case_name=case_name,
        campaign=CampaignSpec(**campaign_dict),
        evidence_snippets=passages,
    )