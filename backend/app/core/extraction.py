"""
Domain-agnostic paper-to-campaign extraction.
Token-safe: passage budget calculated before every LLM call.
No hardcoded parameter names — the LLM maps paper params to tool registry.
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


def extract_case_study_to_campaign(
    document_id: str,
    case_name:   str,
) -> CaseStudyExtraction:
    """
    Extract an executable campaign spec from a paper.

    Domain-agnostic: the LLM reads the paper passages and the tool registry,
    then maps paper parameters to available tools itself.
    No hardcoded parameter names anywhere in this function.
    """
    tool_context = TOOL_REGISTRY.to_llm_context()
    controllable = TOOL_REGISTRY.all_controllable_parameters()
    measurable   = TOOL_REGISTRY.all_measurable_outputs()

    # Calculate passage budget to avoid 413 errors
    prompt_template_chars = 1200
    tool_context_chars    = len(tool_context)
    system_msg_chars      = 400
    response_headroom     = 1200 * 4   # max_tokens * ~4 chars/token
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

    # Also include any tables from the matched section
    doc = get_document(document_id)
    table_context = ""
    if doc.sections:
        for s in doc.sections:
            if case_name.lower() in s.heading.lower():
                tbls = get_tables_for_section(document_id, s.heading)
                if tbls:
                    table_context = "\n\nEXTRACTED TABLES FROM THIS SECTION:\n"
                    for t in tbls[:3]:
                        table_context += f"\nTable caption: {t.caption}\n{t.html}\n"
                break

    prompt = f"""Extract an executable experimental campaign from this paper.

TARGET: "{case_name}"

AVAILABLE LAB TOOLS:
{tool_context}

CONTROLLABLE PARAMETERS (what the lab can set): {controllable}
MEASURABLE OUTPUTS (what the lab can measure): {measurable}

PAPER PASSAGES:
{passages_text}
{table_context}

INSTRUCTIONS:
1. Identify the experimental objective (what is being optimised or measured)
2. Identify the controllable parameters used in this case study
3. Map each paper parameter to the closest name in CONTROLLABLE PARAMETERS
4. Identify the measured outputs and map to MEASURABLE OUTPUTS
5. Extract operating conditions (fixed conditions like power levels, temperatures)
6. Note assumptions made in the mapping

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
      "name": "condition name",
      "values": [<list of numbers>],
      "unit": "unit string",
      "description": "what this condition represents"
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
                    "Output strict JSON only — no markdown, no explanation."
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

    # Feasibility check against live tool registry
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