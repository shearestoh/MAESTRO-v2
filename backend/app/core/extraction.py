"""
Domain-agnostic paper-to-campaign extraction.
"""
from __future__ import annotations

import json
import uuid
from typing import List

import numpy as np

from app.core.documents import get_document, retrieve_relevant_passages
from app.core.llm import call_llm, _MAX_PROMPT_CHARS
from app.core.models import CampaignSpec, CaseStudyExtraction
from app.core.tool_registry import TOOL_REGISTRY

_CONDITION_KEYWORDS = {
    "power", "power_w", "discharge_power", "applied_power", "cell_power",
    "temperature", "temp", "annealing_temp", "reaction_temp", "sintering_temp",
    "current", "c_rate", "voltage", "applied_voltage", "bias",
    "ph", "pressure", "flow_rate", "concentration", "solvent_ratio",
    "reaction_time", "exposure_time", "humidity", "irradiance", "wavelength",
    "load", "strain_rate", "stress", "condition", "level", "setting", "rate",
}


def _looks_like_condition(param: dict) -> bool:
    name = param.get("name", "").lower().replace(" ", "_").replace("-", "_")
    for kw in _CONDITION_KEYWORDS:
        if kw in name:
            return True
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
    p_min = float(param.get("min", 0))
    p_max = float(param.get("max", 1))
    if p_min == p_max:
        return [round(p_min, 4)]
    return [round(float(v), 4) for v in np.linspace(p_min, p_max, 5)]


def _postprocess_campaign_dict(data: dict) -> dict:
    parameter_space      = data.get("parameter_space", [])
    operating_conditions = data.get("operating_conditions", [])

    true_params    = []
    promoted_to_oc = []

    for param in parameter_space:
        if _looks_like_condition(param):
            promoted_to_oc.append(param)
        else:
            true_params.append(param)

    for param in promoted_to_oc:
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
                "description": param.get("description", f"Operating condition: {param.get('name')}"),
            })

    validated_ocs = []
    for oc in operating_conditions:
        values = oc.get("values", [])
        if not values:
            p_min = oc.get("min")
            p_max = oc.get("max")
            if p_min is not None and p_max is not None:
                values = [round(float(v), 4) for v in np.linspace(float(p_min), float(p_max), 5)]
            else:
                continue
        validated_ocs.append({
            "name":        oc.get("name", "condition"),
            "values":      [float(v) for v in values],
            "unit":        oc.get("unit", ""),
            "description": oc.get("description", ""),
        })

    data["parameter_space"]      = true_params
    data["operating_conditions"] = validated_ocs

    if promoted_to_oc:
        promoted_names = [p.get("name") for p in promoted_to_oc]
        data.setdefault("assumptions", []).append(
            f"Parameters {promoted_names} reclassified as operating conditions."
        )

    return data


def extract_case_study_to_campaign(
    document_id: str,
    case_name:   str,
) -> CaseStudyExtraction:
    tool_context = TOOL_REGISTRY.to_llm_context()
    controllable = TOOL_REGISTRY.all_controllable_parameters()
    measurable   = TOOL_REGISTRY.all_measurable_outputs()

    prompt_template_chars = 2000
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
        document_id, query=case_name, top_k=4, max_chars=passage_budget
    )
    passages_text = "\n\n".join(passages)

    doc = get_document(document_id)
    table_context = ""
    if doc.sections:
        for s in doc.sections:
            if case_name.lower() in s.heading.lower():
                tbls = [t for t in doc.tables if t.section == s.heading]
                if tbls:
                    table_context = "\n\nEXTRACTED TABLES:\n"
                    for t in tbls[:3]:
                        table_context += f"\nTable: {t.caption}\n{t.html}\n"
                break

    prompt = f"""Extract an executable experimental campaign from this paper.

TARGET: "{case_name}"

AVAILABLE INSTRUMENTS:
{tool_context}

CONTROLLABLE PARAMETERS: {controllable}
MEASURABLE OUTPUTS: {measurable}

PAPER PASSAGES:
{passages_text}
{table_context}

DISTINCTION:
- FREE PARAMETERS → "parameter_space": variables BO will search over (continuous bounds)
- OPERATING CONDITIONS → "operating_conditions": fixed external values defining separate runs

Return ONLY valid JSON:
{{
  "title": "concise campaign title",
  "target_case_study": "{case_name}",
  "objective_metric": "name matching MEASURABLE OUTPUTS",
  "parameter_space": [
    {{"name": "...", "original_name": "...", "min": 0, "max": 1, "unit": "...", "mapped_to_tool": "..."}}
  ],
  "operating_conditions": [
    {{"name": "...", "values": [0, 1, 2], "unit": "...", "description": "..."}}
  ],
  "desired_outputs": ["..."],
  "assumptions": ["..."],
  "feasibility_notes": "...",
  "provenance": {{
    "objective": ["quoted evidence"],
    "parameter_space": ["quoted evidence"],
    "operating_conditions": ["quoted evidence"]
  }}
}}"""

    msg = call_llm(
        messages=[
            {
                "role":    "system",
                "content": "You are a precise scientific protocol extraction assistant. Output strict JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        tools=None,
    )

    content = (msg.content or "").strip()
    if "```" in content:
        for part in content.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                content = part
                break

    data = json.loads(content)
    data = _postprocess_campaign_dict(data)

    required_params  = [p["name"] for p in data.get("parameter_space", [])]
    required_outputs = [data.get("objective_metric", "")]
    feasibility      = TOOL_REGISTRY.check_feasibility(required_params, required_outputs)

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