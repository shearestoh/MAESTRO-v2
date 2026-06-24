"""
Domain-agnostic paper-to-campaign extraction.

The key change from v1: we no longer hardcode 'active_material' and 'porosity'.
Instead we:
1. Tell the LLM what tools are available (from the registry)
2. Ask it to extract whatever parameters the paper uses
3. Ask it to map those parameters to available tools
4. Let the feasibility checker determine if execution is possible

The LLM does the domain reasoning. The code stays domain-agnostic.
"""
import json
import uuid

from app.core.documents import retrieve_relevant_passages
from app.core.llm import call_llm
from app.core.models import CampaignSpec, CaseStudyExtraction
from app.core.tool_registry import TOOL_REGISTRY


def extract_case_study_to_campaign(
    document_id: str,
    case_name:   str,
) -> CaseStudyExtraction:
    """
    Extract an executable campaign spec from a paper.

    Domain-agnostic: the LLM reads the paper and the tool registry,
    then figures out the mapping itself. No hardcoded parameter names.
    """
    # Retrieve relevant passages using the case name as the query
    passages = retrieve_relevant_passages(document_id, case_name, top_k=8)

    # Build tool context from registry — not hardcoded
    tool_context = TOOL_REGISTRY.to_llm_context()
    controllable = TOOL_REGISTRY.all_controllable_parameters()
    measurable   = TOOL_REGISTRY.all_measurable_outputs()

    prompt = f"""You are extracting an executable experimental campaign from a scientific paper.

TARGET: Extract the campaign described in "{case_name}".

AVAILABLE LAB TOOLS:
{tool_context}

CONTROLLABLE PARAMETERS (what the lab can set): {controllable}
MEASURABLE OUTPUTS (what the lab can measure): {measurable}

PAPER PASSAGES:
{chr(10).join(passages)}

INSTRUCTIONS:
1. Identify the experimental objective (what is being optimised or measured)
2. Identify the controllable parameters used in this case study
3. Identify the measured outputs
4. Map each paper parameter to the closest available lab tool parameter
5. If a parameter cannot be mapped, list it as missing
6. Extract the operating conditions (e.g. fixed conditions like power levels)
7. Note any assumptions made in the mapping

Return ONLY valid JSON (no markdown fences, no commentary):
{{
  "title": "concise campaign title",
  "target_case_study": "{case_name}",
  "objective_metric": "name of the primary output being optimised",
  "parameter_space": [
    {{
      "name": "parameter_name_matching_lab_tool",
      "original_name": "name as used in the paper",
      "min": <number>,
      "max": <number>,
      "unit": "unit string",
      "mapped_to_tool": "ToolName or null if unmappable"
    }}
  ],
  "operating_conditions": [
    {{
      "name": "condition_name",
      "values": [<list of values>],
      "unit": "unit string",
      "description": "what this condition represents"
    }}
  ],
  "desired_outputs": ["list of expected result types"],
  "assumptions": ["list of assumptions made in mapping paper to lab"],
  "feasibility_notes": "brief assessment of whether the lab can execute this",
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
                    "Extract only what is explicitly stated or strongly implied by the paper. "
                    "Output strict JSON only — no markdown, no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        tools=None,
    )

    content = (msg.content or "").strip()
    # Strip any accidental markdown fences
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    data = json.loads(content)

    # Run feasibility check against the live tool registry
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

    campaign = CampaignSpec(**campaign_dict)

    return CaseStudyExtraction(
        document_id=document_id,
        case_name=case_name,
        campaign=campaign,
        evidence_snippets=passages,
    )