from __future__ import annotations

import io
import json
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


def _cache_path(document_id: str) -> str:
    cache_dir = os.path.join(os.path.dirname(_MEDIA_DIR), "doc_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{document_id}.json")


def _save_doc_cache(doc: DocumentModel) -> None:
    try:
        # Derive pages from sections so cache is self-contained without raw_text
        pages_from_sections = [s.content for s in doc.sections if s.content]
        cache = {
            "document_id": doc.document_id,
            "filename":    doc.filename,
            "title":       doc.title,
            "uploaded_at": doc.uploaded_at,
            "summary":     doc.summary,
            "authors":     doc.authors,
            "year":        doc.year,
            "doi":         doc.doi,
            "journal":     doc.journal,
            "pages":       pages_from_sections,
            "sections":    [s.model_dump() for s in doc.sections],
            "figures":     [f.model_dump() for f in doc.figures],
            "tables":      [t.model_dump() for t in doc.tables],
        }
        with open(_cache_path(doc.document_id), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Could not cache document {doc.document_id}: {e}")


def _load_doc_cache(document_id: str, filename: str) -> DocumentModel | None:
    path = _cache_path(document_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        sections = [SectionModel(**s) for s in data.get("sections", [])]
        # Reconstruct pages from sections if not explicitly stored
        pages = data.get("pages") or [s.content for s in sections if s.content]
        return DocumentModel(
            document_id=data["document_id"],
            filename=data.get("filename", filename),
            title=data.get("title"),
            uploaded_at=data.get("uploaded_at"),
            summary=data.get("summary"),
            authors=data.get("authors", []),
            year=data.get("year"),
            doi=data.get("doi"),
            journal=data.get("journal"),
            pages=pages,
            sections=sections,
            figures=[FigureModel(**f) for f in data.get("figures", [])],
            tables=[],
        )
    except Exception as e:
        print(f"[WARN] Could not load document cache for {document_id}: {e}")
        return None


def _extract_paper_metadata(markdown: str) -> dict:
    """
    Extract authors, year, DOI, and journal from raw markdown text.
    Handles both comma-delimited author lines and stacked single-name-per-line formats.
    Generic — no paper-specific content hardcoded.
    """
    metadata: dict = {}
    search_text = markdown[:8000]

    # ── DOI ──────────────────────────────────────────────────────────────────
    doi_match = re.search(
        r'(?:doi\.org/|doi[:\s/]+)(10\.\d{4,}/[^\s\)\]>,"\']+)',
        search_text, re.IGNORECASE,
    )
    if doi_match:
        metadata["doi"] = doi_match.group(1).rstrip(".")

    # ── Year ─────────────────────────────────────────────────────────────────
    year_match = re.search(
        r'(?:published|received|accepted|©|copyright|\b(?:jan|feb|mar|apr|may|jun|'
        r'jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?\b(20[0-2]\d|19[89]\d)\b',
        search_text, re.IGNORECASE,
    )
    if year_match:
        metadata["year"] = int(year_match.group(1))
    else:
        fallback = re.search(r'\b(20[0-2]\d|19[89]\d)\b', search_text)
        if fallback:
            metadata["year"] = int(fallback.group(1))

    # ── Journal ───────────────────────────────────────────────────────────────
    for pat in [
        r'(?:journal of|nature|science|physical review|advanced|ACS|RSC|Elsevier|Wiley)[^\n]{3,60}',
        r'(?:published in|journal)[:\s]+([^\n]{5,80})',
    ]:
        m = re.search(pat, search_text, re.IGNORECASE)
        if m:
            candidate = m.group(0).strip()[:100]
            if len(candidate) > 5:
                metadata["journal"] = candidate
                break

    # ── Authors ───────────────────────────────────────────────────────────────
    # Signals that a line is an affiliation, address, or non-author content.
    AFFILIATION_SIGNALS = re.compile(
        r'university|institute|college|school|department|laboratory|lab\b|'
        r'centre|center|faculty|division|'
        r'road|street|avenue|boulevard|lane|drive|'
        r'sw\d|ec\d|wc\d|[a-z]{1,2}\d{1,2}\s*\d[a-z]{2}|'  # UK postcodes
        r'\d{5}|'                                              # US zip codes
        r'@[a-z]+\.[a-z]+|'                                   # email
        r'\.ac\.|\.edu|\.org|\.gov|'
        r'correspondence|contact|lead contact|'
        r'orcid|https?://',
        re.IGNORECASE,
    )

    # A single person name: Firstname [Initial.] Lastname
    # Must start with capital, contain only letters/hyphens/dots, no digits.
    SINGLE_NAME = re.compile(
        r'^[A-Z][a-záàâäãåçéèêëíìîïñóòôöõúùûü][a-záàâäãåçéèêëíìîïñóòôöõúùûü\-]{0,25}'
        r'(?:\s+[A-Z]\.?)?'
        r'(?:\s+[A-Z][a-záàâäãåçéèêëíìîïñóòôöõúùûü\-]{1,25})?$',
        re.UNICODE,
    )

    def is_affiliation(line: str) -> bool:
        if AFFILIATION_SIGNALS.search(line):
            return True
        # Lines starting with a digit followed by a capital (e.g. "1Polaron, Oxfordshire")
        if re.match(r'^\d+[A-Z]', line.strip()):
            return True
        # Very long lines are abstracts or affiliations
        if len(line.strip()) > 100:
            return True
        return False

    def clean_name(raw: str) -> str:
        """Strip superscripts, footnote markers, and leading digits from a name token."""
        cleaned = re.sub(r'[\d\*†‡§¶#,]+$', '', raw.strip())
        cleaned = re.sub(r'^[\d\*†‡§¶#,]+', '', cleaned).strip()
        return cleaned

    def is_valid_name(token: str) -> bool:
        return bool(SINGLE_NAME.match(token)) and 2 < len(token) < 60

    lines = search_text.splitlines()
    best_authors: list[str] = []

    # ── Strategy 1: comma-delimited author line ───────────────────────────────
    # e.g. "Steve Kench, Isaac Squires, Amir Dahari, ..."
    for line in lines[:80]:
        stripped = line.strip()
        if not stripped or is_affiliation(stripped):
            continue
        parts = re.split(r'[,;]|\band\b', stripped)
        parts = [clean_name(p) for p in parts if clean_name(p)]
        if len(parts) < 2:
            continue
        valid = [p for p in parts if is_valid_name(p)]
        if len(valid) >= 2 and len(valid) >= len(parts) * 0.6:
            if len(valid) > len(best_authors):
                best_authors = valid[:20]

    # ── Strategy 2: stacked single-name-per-line block ───────────────────────
    # e.g.:
    #   Ge Lei
    #   Dyson School of Design Engineering   ← affiliation, skip
    #   Imperial College London              ← affiliation, skip
    #   Samuel J. Cooper
    # Collect all lines that look like a single person name and are NOT affiliations.
    if len(best_authors) < 2:
        stacked: list[str] = []
        for line in lines[:120]:
            stripped = line.strip()
            if not stripped:
                continue
            if is_affiliation(stripped):
                continue
            candidate = clean_name(stripped)
            if is_valid_name(candidate):
                stacked.append(candidate)

        # Accept the stacked list if we found at least 2 names
        if len(stacked) >= 2 and len(stacked) > len(best_authors):
            best_authors = stacked[:20]

    # ── Strategy 3: "Authors:" prefix ────────────────────────────────────────
    if len(best_authors) < 2:
        m = re.search(r'(?:authors?|by)[:\s]+([^\n]{10,200})', search_text[:4000], re.IGNORECASE)
        if m:
            parts = re.split(r'[;,]|\s+and\s+', m.group(1))
            valid = [clean_name(p) for p in parts if is_valid_name(clean_name(p))]
            if len(valid) >= 2:
                best_authors = valid[:20]

    if best_authors:
        metadata["authors"] = best_authors

    return metadata


def _extract_with_mineru(
    file_bytes: bytes,
) -> Tuple[str, List[SectionModel], List[FigureModel], List[TableModel]]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path   = os.path.join(tmp_dir, "input.pdf")
        output_dir = os.path.join(tmp_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        with open(pdf_path, "wb") as f:
            f.write(file_bytes)

        try:
            result = subprocess.run(
                ["mineru", "-p", pdf_path, "-o", output_dir, "-b", "pipeline"],
                capture_output=True, text=True, timeout=300,
            )
        except FileNotFoundError:
            raise RuntimeError("MinerU binary not found. Install with: pip install mineru")

        if result.returncode != 0:
            raise RuntimeError(f"MinerU failed: {result.stderr[:500]}")

        md_path = cl_path = None
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
                content_list = json.load(f)

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
                    img_map[img_fname]             = dest
                    img_map[f"images/{img_fname}"] = dest
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
    return title.strip() if isinstance(title, str) else ""


def _enrich_captions_from_markdown(
    markdown: str,
    figures:  List[FigureModel],
) -> List[FigureModel]:
    lines = markdown.splitlines()
    figure_caption_map: dict[str, str] = {}

    for i, line in enumerate(lines):
        m = re.match(r'^(Fig(?:ure)?\.?\s*\d+[A-Za-z]?)[\.:\s](.+)$', line.strip(), re.IGNORECASE)
        if m:
            caption = (m.group(1) + ". " + m.group(2)).strip()
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("#") and not next_line.startswith("!"):
                    caption += " " + next_line
                else:
                    break
            figure_caption_map[m.group(1).strip().lower()] = caption[:300]

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
                if next_line and not next_line.startswith("!") and len(next_line) > 10:
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
        for fig, (_, caption) in zip(sorted(uncaptioned, key=lambda f: f.page_idx), sorted_captions):
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
            img_abs      = img_map.get(img_fname, "") or img_map.get(img_path_rel, "")
            fig_id       = str(uuid.uuid4())
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


def create_document(filename: str, file_bytes: bytes, document_id: str | None = None) -> DocumentModel:
    if document_id:
        cached = _load_doc_cache(document_id, filename)
        if cached:
            DOCUMENTS[document_id] = cached
            return cached

    try:
        markdown, sections, figures, tables = _extract_with_mineru(file_bytes)
    except Exception as e:
        raise RuntimeError(
            f"Document parsing failed: {e}. "
            "Ensure MinerU is installed: pip install mineru"
        )

    title = filename
    for s in sections:
        if s.level == 1 and len(s.heading) > 5:
            title = s.heading
            break
    if title == filename:
        lines = [l.strip() for l in markdown.splitlines() if l.strip()]
        title = next((l[:300] for l in lines[:15] if len(l) > 20), filename)

    metadata = _extract_paper_metadata(markdown)
    # Derive pages from sections so cache reloads work without raw_text
    pages = [s.content for s in sections if s.content]

    doc = DocumentModel(
        document_id=document_id or str(uuid.uuid4()),
        filename=filename,
        title=title,
        raw_text=markdown,
        pages=pages,
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
    _save_doc_cache(doc)
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
    top_k:       int = 3,
    max_chars:   int = 1500,
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
    top = scored[:top_k] or [(0, i, s) for i, s in enumerate(sections) if s.content.strip()][:top_k]

    per_budget = max(300, max_chars // max(len(top), 1))
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
    top = scored[:top_k] or [(0, i, p) for i, p in enumerate(pages) if p.strip()][:top_k]
    per_budget = max(300, max_chars // max(len(top), 1))
    return [f"[Page {i + 1}]\n{page[:per_budget]}" for _, i, page in top]


def get_document_summary_chunk(document_id: str, max_chars: int = 1500) -> str:
    doc = get_document(document_id)

    meta_lines = []
    if doc.authors:
        meta_lines.append(f"Authors: {', '.join(doc.authors)}")
    if doc.year:
        meta_lines.append(f"Year: {doc.year}")
    if doc.doi:
        meta_lines.append(f"DOI: {doc.doi}")
    meta_block = ("\n".join(meta_lines) + "\n\n") if meta_lines else ""
    remaining  = max_chars - len(meta_block)

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