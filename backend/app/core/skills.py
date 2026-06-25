"""
LLM-powered skills: document summarisation, campaign description.
All calls are token-safe — use compact inputs only.
"""
from __future__ import annotations

import json

from app.core.documents import get_document_summary_chunk
from app.core.llm import call_llm
from app.core.models import CampaignSpec, DocumentModel


def summarise_uploaded_document(doc: DocumentModel) -> str:
    """
    Summarise a paper in 2-4 sentences.
    Uses only abstract/intro (~3000 chars) — enough for a summary.
    """
    chunk = get_document_summary_chunk(doc.document_id, max_chars=3000)

    msg = call_llm(
        messages=[
            {
                "role":    "system",
                "content": "Summarise scientific papers clearly and concisely.",
            },
            {
                "role":    "user",
                "content": (
                    f"Summarise this paper in 2-4 sentences. "
                    f"Note if it contains optimisation case studies "
                    f"that could be reproduced in a virtual lab.\n\n"
                    f"Filename: {doc.filename}\n\n"
                    f"Content:\n{chunk}"
                ),
            },
        ],
        tools=None,
    )
    return (msg.content or "").strip()


def describe_extracted_campaign(campaign: CampaignSpec) -> str:
    """
    Describe an extracted campaign in plain language.
    Uses the structured campaign dict — no raw paper text needed.
    """
    compact = {
        "title":                campaign.title,
        "target_case_study":    campaign.target_case_study,
        "objective_metric":     campaign.objective_metric,
        "parameter_space":      campaign.parameter_space,
        "operating_conditions": campaign.operating_conditions,
        "capability_match":     campaign.capability_match,
        "assumptions":          campaign.assumptions[:3],
    }

    msg = call_llm(
        messages=[
            {
                "role":    "system",
                "content": "Describe scientific campaign plans naturally and concisely.",
            },
            {
                "role":    "user",
                "content": (
                    f"Describe this campaign in 3-5 sentences. Explain:\n"
                    f"- What case study was identified\n"
                    f"- What variables and conditions were inferred\n"
                    f"- Whether the virtual lab can reproduce it\n"
                    f"- That the workflow can be executed upon approval\n\n"
                    f"Campaign:\n{json.dumps(compact, indent=2)}"
                ),
            },
        ],
        tools=None,
    )
    return (msg.content or "").strip()