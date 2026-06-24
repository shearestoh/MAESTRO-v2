"""LLM-powered skills: document summarisation, campaign description."""
import json
from app.core.documents import retrieve_relevant_passages
from app.core.llm import call_llm
from app.core.models import CampaignSpec, DocumentModel


def summarise_uploaded_document(doc: DocumentModel) -> str:
    passages = [p for p in doc.pages if p.strip()][:3]
    msg = call_llm(
        messages=[
            {"role": "system", "content": "Summarise scientific papers clearly and concisely."},
            {"role": "user", "content": (
                f"Summarise this paper in 2-4 sentences. Note if it contains "
                f"optimisation case studies reproducible in a virtual lab.\n\n"
                f"Filename: {doc.filename}\n\nPassages:\n" + "\n".join(passages)[:8000]
            )},
        ],
        tools=None,
    )
    return (msg.content or "").strip()


def describe_extracted_campaign(campaign: CampaignSpec) -> str:
    msg = call_llm(
        messages=[
            {"role": "system", "content": "Describe scientific campaign plans naturally."},
            {"role": "user", "content": (
                f"Describe this campaign in 3-5 sentences. Explain what was identified, "
                f"what variables were inferred, and that it can be executed upon approval.\n\n"
                f"Campaign:\n{json.dumps(campaign.model_dump(), indent=2)}"
            )},
        ],
        tools=None,
    )
    return (msg.content or "").strip()