"""PDF ingestion and passage retrieval for RAG."""
import io
import uuid
from datetime import datetime
from typing import Dict, List

from PyPDF2 import PdfReader
from app.core.models import DocumentModel

DOCUMENTS: Dict[str, DocumentModel] = {}


def extract_pdf_text(file_bytes: bytes) -> List[str]:
    reader = PdfReader(io.BytesIO(file_bytes))
    return [page.extract_text() or "" for page in reader.pages]


def create_document(filename: str, file_bytes: bytes) -> DocumentModel:
    pages    = extract_pdf_text(file_bytes)
    raw_text = "\n\n".join(pages)
    lines    = [l.strip() for l in raw_text.splitlines() if l.strip()]
    title    = next((l[:300] for l in lines[:25] if len(l) > 20), filename)
    doc = DocumentModel(
        document_id=str(uuid.uuid4()), filename=filename, title=title,
        raw_text=raw_text, pages=pages, uploaded_at=datetime.utcnow().isoformat(),
    )
    DOCUMENTS[doc.document_id] = doc
    return doc


def get_document(document_id: str) -> DocumentModel:
    if document_id not in DOCUMENTS:
        raise KeyError(f"Unknown document_id: {document_id}")
    return DOCUMENTS[document_id]


def retrieve_relevant_passages(document_id: str, query: str, top_k: int = 5) -> List[str]:
    """Simple TF-style passage retrieval — score pages by query term frequency."""
    doc     = get_document(document_id)
    q_terms = [t.lower() for t in query.split() if t.strip()]
    scored  = []
    for i, page in enumerate(doc.pages):
        score = sum(page.lower().count(t) for t in q_terms)
        if score > 0:
            scored.append((score, i, page))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:top_k] or [(0, i, p) for i, p in enumerate(doc.pages) if p.strip()][:top_k]
    return [f"[Page {i+1}]\n{page[:4000]}" for _, i, page in top]