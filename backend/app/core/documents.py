"""
Document ingestion using MinerU.

MinerU provides structured extraction of sections, figures, and tables
from scientific PDFs, enabling RAG and campaign extraction.

Install MinerU with: pip install mineru
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.core.models import DocumentModel, FigureModel, SectionModel, TableModel

DOCUMENTS: Dict[str, DocumentModel] = {}

_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "maestro_media")
os.makedirs(_MEDIA_DIR, exist_ok=True)


def _extract_paper_metadata(markdown: str) -> dict:
    """
    Extract authors, year, DOI, and journal from the raw markdown text.
    Searches the first ~8000 characters where metadata typically appears.
    """
    metadata: dict = {}
    search_text = markdown[:8000]

    # DOI
    doi_match = re.search(
        r'(?:doi\.org/|doi[:\s/]+)(10\.\d{4,}/[^\s\)\]>,"\']+)',
        search_text, re.IGNORECASE
    )
    if doi_match:
        metadata["doi"] = doi_match.group(1).rstrip(".")

    # Year — prefer 4-digit year in 2000–2030 range near publication keywords
    year_match = re.search(
        r'(?:published|received|accepted|©|copyright|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?\b(20[0-2]\d|19[89]\d)\b',
        search_text, re.IGNORECASE
    )
    if year_match:
        metadata["year"] = int(year_match.group(1))
    else:
        # Fallback: first 4-digit year in range
        fallback = re.search(r'\b(20[0-2]\d|19[89]\d)\b', search_text)
        if fallback:
            metadata["year"] = int(fallback.group(1))

    # Journal — look for common journal name patterns
    journal_patterns = [
        r'(?:journal of|nature|science|physical review|advanced|ACS|RSC|Elsevier|Wiley)[^\n]{3,60}',
        r'(?:published in|journal)[:\s]+([^\n]{5,80})',
    ]
    for pat in journal_patterns:
        m = re.search(pat, search_text, re.IGNORECASE)
        if m:
            candidate = m.group(0).strip()[:100]
            if len(candidate) > 5:
                metadata["journal"] = candidate
                break

    # Authors — heuristic: look for lines with multiple capitalised names
    # Typical patterns: "John Smith, Jane Doe, ..." or "Smith J., Doe J.A., ..."
    author_patterns = [
        # "Firstname Lastname, Firstname Lastname" style
        r'^([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:,\s*[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+){1,})',
        # "Lastname, F., Lastname, F." style
        r'^([A-Z][a-z]+,\s+[A-Z]\.(?:,\s+[A-Z][a-z]+,\s+[A-Z]\.){1,})',
        # After "Authors:" or "By:"
        r'(?:authors?|by)[:\s]+([^\n]{10,200})',
    ]
    for pat in author_patterns:
        m = re.search(pat, search_text[:4000], re.MULTILINE | re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Split on comma or semicolon or " and "
            parts = re.split(r'[;]|,\s*(?:and\s+)?|\s+and\s+', raw)
            authors = [p.strip() for p in parts if len(p.strip()) > 2 and len(p.strip()) < 60]
            if len(authors) >= 2:
                metadata["authors"] = authors[:20]
                break

    return metadata


def _extract_with_mineru(
    file_bytes: bytes,
) -> Tuple[str, List[SectionModel], List[FigureModel], List[TableModel]]:
    import json as _json

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path   = os.path.join(tmp_dir, "input.pdf")
        output_dir = os.path.join(tmp_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        with open(pdf_path, "wb") as f:
            f.write(file_bytes)

        try:
            result = subprocess.run(
                ["mineru", "-p", pdf_path, "-o", output_dir, "-b", "pipeline"],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "MinerU binary not found. Install with: pip install mineru"
            )

        if result.returncode != 0:
            raise RuntimeError(f"MinerU failed: {result.stderr[:500]}")

        md_path = None
        cl_path = None
        for root, _, files in os.walk(output_dir):
            for fname in files:
                if fname.endswith(".md") and md_path is None:
                    md_path = os.path.join(root, fname)
                if fname.endswith("_content_list.json") and cl_path is None:
                    cl_path = os.path.join(root, fname)

        if md_path is None:
            raise RuntimeError("MinerU produced no markdown output")

        with open(md_path, encoding="utf-8") as f:
            markdown = f.read()

        content_list = []
        if cl_path and os.path.exists(cl_path):
            with open(cl_path, encoding="utf-8") as f:
                content_list = _json.load(f)

        img_src_dir = os.path.join(os.path.dirname(md_path), "images")
        img_map: Dict[str, str] = {}

        if os.path.isdir(img_src_dir):
            import shutil
            for img_fname in os.listdir(img_src_dir):
                if not img_fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    continue
                src  = os.path.join(img_src_dir, img_fname)
                dest = os.path.join(_MEDIA_DIR, img_fname)
                try:
                    shutil.copy2(src, dest)
                    img_map[img_fname]                         = dest
                    img_map[f"images/{img_fname}"]             = dest
                    img_map[os.path.join("images", img_fname)] = dest
                except Exception as e:
                    print(f"[WARN] Could not copy image {img_fname}: {e}")

        sections, figures, tables = _parse_mineru_output(markdown, content_list, img_map)
        return markdown, sections, figures, tables


def _extract_caption(item: dict) -> str:
    for field in ("image_caption", "img_caption", "figure_caption", "caption"):
        parts = item.get(field, [])
        if isinstance(parts, str) and parts.strip():
            return parts.strip()
        if isinstance(parts, list) and parts:
            texts = []
            for p in parts:
                if isinstance(p, str):
                    texts.append(p)
                elif isinstance(p, dict):
                    for key in ("text", "content", "value", "c"):
                        if isinstance(p.get(key), str) and p[key].strip():
                            texts.append(p[key])
                            break
            result = " ".join(texts).strip()
            if result:
                return result
    title = item.get("title", "")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return ""


def _enrich_captions_from_markdown(
    markdown: str,
    figures:  List[FigureModel],
) -> List[FigureModel]:
    lines = markdown.splitlines()

    figure_caption_map: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = re.match(
            r'^(Fig(?:ure)?\.?\s*\d+[A-Za-z]?)[\.:\s](.+)$',
            line.strip(),
            re.IGNORECASE,
        )
        if m:
            fig_ref = m.group(1).strip()
            caption = (m.group(1) + ". " + m.group(2)).strip()
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("#") and not next_line.startswith("!"):
                    caption += " " + next_line
                else:
                    break
            figure_caption_map[fig_ref.lower()] = caption[:300]

    for fig in figures:
        if fig.caption:
            continue
        img_fname = os.path.basename(fig.path) if fig.path else ""
        if not img_fname:
            continue
        for i, line in enumerate(lines):
            if img_fname not in line or not line.strip().startswith("!"):
                continue
            inline = re.match(r'!\[([^\]]+)\]', line)
            if inline and len(inline.group(1).strip()) > 5:
                fig.caption = inline.group(1).strip()
                break
            for j in range(i + 1, min(i + 6, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("!") and not next_line.startswith("#") and len(next_line) > 10:
                    fig.caption = next_line[:200]
                    break
            if fig.caption:
                break

    uncaptioned = [f for f in figures if not f.caption]
    if uncaptioned and figure_caption_map:
        sorted_captions = sorted(
            figure_caption_map.items(),
            key=lambda x: int(re.search(r'\d+', x[0]).group()) if re.search(r'\d+', x[0]) else 999,
        )
        uncaptioned_sorted = sorted(uncaptioned, key=lambda f: f.page_idx)
        for fig, (_, caption) in zip(uncaptioned_sorted, sorted_captions):
            if not fig.caption:
                fig.caption = caption

    for fig in figures:
        if not fig.caption:
            fig.caption = f"Figure (page {fig.page_idx + 1})"

    return figures


def _parse_mineru_output(
    markdown:     str,
    content_list: list,
    img_map:      Dict[str, str],
) -> Tuple[List[SectionModel], List[FigureModel], List[TableModel]]:
    sections: List[SectionModel] = []
    figures:  List[FigureModel]  = []
    tables:   List[TableModel]   = []

    current_heading = "Introduction"
    current_level   = 2
    current_lines:  List[str] = []

    for line in markdown.splitlines():
        m = re.match(r'^(#{1,4})\s+(.+)$', line.strip())
        if m:
            if current_lines:
                sections.append(SectionModel(
                    heading=current_heading,
                    level=current_level,
                    content="\n".join(current_lines).strip(),
                ))
            current_heading = m.group(2).strip()
            current_level   = len(m.group(1))
            current_lines   = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(SectionModel(
            heading=current_heading,
            level=current_level,
            content="\n".join(current_lines).strip(),
        ))

    for item in content_list:
        item_type = item.get("type", "")
        page_idx  = item.get("page_idx", 0)

        if item_type in ("image", "figure"):
            caption      = _extract_caption(item)
            img_path_rel = item.get("img_path", "")
            img_fname    = os.path.basename(img_path_rel)
            img_abs      = img_map.get(img_fname, "")
            if not img_abs and img_path_rel:
                img_abs = img_map.get(img_path_rel, "")
            fig_id = str(uuid.uuid4())
            figures.append(FigureModel(
                figure_id=fig_id,
                page_idx=page_idx,
                caption=caption,
                path=img_abs,
                served_url=f"/media/{fig_id}",
            ))

        elif item_type == "table":
            caption_parts = item.get("table_caption", [])
            caption = " ".join(
                c if isinstance(c, str) else c.get("text", "")
                for c in caption_parts
            ).strip()
            tbl_id = str(uuid.uuid4())
            tables.append(TableModel(
                table_id=tbl_id,
                page_idx=page_idx,
                caption=caption,
                html=item.get("table_body", ""),
            ))

    if sections and (figures or tables):
        for fig in figures:
            fig.section = _find_section_for_caption(fig.caption, sections)
        for tbl in tables:
            tbl.section = _find_section_for_caption(tbl.caption, sections)

    if figures:
        figures = _enrich_captions_from_markdown(markdown, figures)

    return sections, figures, tables


def _find_section_for_caption(caption: str, sections: List[SectionModel]) -> str:
    if not caption:
        return ""
    cap_lower = caption.lower()
    for s in sections:
        if cap_lower[:50] in s.content.lower():
            return s.heading
    return sections[-1].heading if sections else ""


def create_document(filename: str, file_bytes: bytes) -> DocumentModel:
    try:
        markdown, sections, figures, tables = _extract_with_mineru(file_bytes)
    except Exception as e:
        raise RuntimeError(
            f"Document parsing failed: {e}. "
            "Ensure MinerU is installed: pip install mineru"
        )

    # Extract paper title
    title = filename
    for s in sections:
        if s.level == 1 and len(s.heading) > 5:
            title = s.heading
            break
    if title == filename:
        lines = [l.strip() for l in markdown.splitlines() if l.strip()]
        title = next((l[:300] for l in lines[:15] if len(l) > 20), filename)

    # Extract paper metadata (authors, year, DOI, journal)
    metadata = _extract_paper_metadata(markdown)

    doc = DocumentModel(
        document_id=str(uuid.uuid4()),
        filename=filename,
        title=title,
        raw_text=markdown,
        pages=[s.content for s in sections if s.content],
        uploaded_at=datetime.utcnow().isoformat(),
        sections=sections,
        figures=figures,
        tables=tables,
        authors=metadata.get("authors", []),
        year=metadata.get("year"),
        doi=metadata.get("doi"),
        journal=metadata.get("journal"),
    )
    DOCUMENTS[doc.document_id] = doc
    return doc


def get_document(document_id: str) -> DocumentModel:
    if document_id not in DOCUMENTS:
        raise KeyError(f"Unknown document_id: {document_id}")
    return DOCUMENTS[document_id]


def get_figure(figure_id: str) -> Optional[FigureModel]:
    for doc in DOCUMENTS.values():
        for fig in doc.figures:
            if fig.figure_id == figure_id:
                return fig
    return None


def retrieve_relevant_passages(
    document_id: str,
    query:       str,
    top_k:       int = 4,
    max_chars:   int = 6000,
) -> List[str]:
    doc = get_document(document_id)
    if doc.sections:
        return _retrieve_from_sections(doc.sections, query, top_k, max_chars)
    return _retrieve_from_pages(doc.pages, query, top_k, max_chars)


def _retrieve_from_sections(
    sections:  List[SectionModel],
    query:     str,
    top_k:     int,
    max_chars: int,
) -> List[str]:
    q_lower = query.lower()
    q_terms = [t.lower() for t in query.split() if len(t) > 2]
    scored:  List[tuple] = []

    for i, s in enumerate(sections):
        h = s.heading.lower()
        c = s.content.lower()
        if q_lower in h:
            score = 10000
        elif all(t in h for t in q_terms):
            score = 5000
        elif any(t in h for t in q_terms):
            score = 1000 + sum(h.count(t) for t in q_terms)
        else:
            score = sum(c.count(t) for t in q_terms)
        if score > 0:
            scored.append((score, i, s))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:top_k] or [
        (0, i, s) for i, s in enumerate(sections) if s.content.strip()
    ][:top_k]

    per_budget = max(500, max_chars // max(len(top), 1))
    return [f"## {s.heading}\n\n{s.content}"[:per_budget] for _, _, s in top]


def _retrieve_from_pages(
    pages:     List[str],
    query:     str,
    top_k:     int,
    max_chars: int,
) -> List[str]:
    q_terms = [t.lower() for t in query.split() if len(t) > 2]
    scored  = []
    for i, page in enumerate(pages):
        if not page.strip():
            continue
        score = sum(page.lower().count(t) for t in q_terms)
        if score > 0:
            scored.append((score, i, page))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:top_k] or [
        (0, i, p) for i, p in enumerate(pages) if p.strip()
    ][:top_k]
    per_budget = max(500, max_chars // max(len(top), 1))
    return [f"[Page {i + 1}]\n{page[:per_budget]}" for _, i, page in top]


def get_document_summary_chunk(document_id: str, max_chars: int = 3000) -> str:
    doc = get_document(document_id)

    # Build metadata header
    meta_lines = []
    if doc.authors:
        meta_lines.append(f"Authors: {', '.join(doc.authors)}")
    if doc.year:
        meta_lines.append(f"Year: {doc.year}")
    if doc.doi:
        meta_lines.append(f"DOI: {doc.doi}")
    if doc.journal:
        meta_lines.append(f"Journal: {doc.journal}")
    meta_block = ("\n".join(meta_lines) + "\n\n") if meta_lines else ""

    remaining = max_chars - len(meta_block)

    if doc.sections:
        priority = {"abstract", "introduction", "overview", "summary", "background"}
        chunk    = ""
        for s in doc.sections[:6]:
            if any(kw in s.heading.lower() for kw in priority):
                chunk += f"## {s.heading}\n{s.content}\n\n"
                if len(chunk) >= remaining:
                    break
        if not chunk:
            for s in doc.sections[:3]:
                chunk += f"## {s.heading}\n{s.content}\n\n"
                if len(chunk) >= remaining:
                    break
        return (meta_block + chunk)[:max_chars].strip()

    chunk = ""
    for page in doc.pages[:3]:
        if len(chunk) + len(page) > remaining:
            chunk += page[:remaining - len(chunk)]
            break
        chunk += page + "\n\n"
    return (meta_block + chunk).strip()


def get_all_library_context(max_chars_per_doc: int = 800) -> str:
    """
    Build a compact context string from all loaded documents for the system prompt.
    Includes metadata (authors, year, DOI) to support bibliographic queries.
    """
    if not DOCUMENTS:
        return ""
    lines = ["KNOWLEDGE LIBRARY:\n"]
    for doc in DOCUMENTS.values():
        chunk = get_document_summary_chunk(doc.document_id, max_chars=max_chars_per_doc)
        lines.append(f"--- {doc.title or doc.filename} ---")
        lines.append(chunk)
        lines.append("")
    return "\n".join(lines)