"""
Document ingestion with MinerU (Phase 2B) + PyPDF2 fallback.

MinerU v3.4 is detected at runtime — if not installed, PyPDF2 is used.
Both paths produce the same DocumentModel shape, so all downstream code
works identically regardless of which parser ran.

Key Phase 2B additions:
- SectionModel: heading-level structure for deterministic case study lookup
- FigureModel: extracted images with captions, served via /media/{figure_id}
- TableModel: extracted HTML tables with captions
- Section-aware retrieval: "Case Study 2" → exact heading match
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.core.models import (
    DocumentModel,
    FigureModel,
    SectionModel,
    TableModel,
)

# In-memory document store (one per server process)
DOCUMENTS: Dict[str, DocumentModel] = {}

# Persistent media directory for extracted figures
_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "maestro_media")
os.makedirs(_MEDIA_DIR, exist_ok=True)


# ── MinerU availability ───────────────────────────────────────────────────────

def _check_mineru() -> bool:
    try:
        import mineru  # noqa: F401
        return True
    except ImportError:
        return False


MINERU_AVAILABLE = _check_mineru()


# ── MinerU extraction ─────────────────────────────────────────────────────────

def _extract_with_mineru(file_bytes: bytes) -> Tuple[str, List[SectionModel], List[FigureModel], List[TableModel]]:
    """
    Extract structured content from PDF using MinerU pipeline backend.
    Returns (markdown, sections, figures, tables).

    Uses the pipeline backend (CPU-safe, no GPU required)  ^1^ .
    MinerU v3.4 API: mineru CLI or Python via mineru-api  ^2^ .
    """
    import subprocess
    import json as _json

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path    = os.path.join(tmp_dir, "input.pdf")
        output_dir  = os.path.join(tmp_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        with open(pdf_path, "wb") as f:
            f.write(file_bytes)

        # Use MinerU CLI — most stable interface across versions  ^2^ 
        result = subprocess.run(
            [
                "mineru",
                "-p", pdf_path,
                "-o", output_dir,
                "-b", "pipeline",   # CPU-safe backend  ^1^ 
            ],
            capture_output=True,
            text=True,
            timeout=300,            # 5 min max for large papers
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"MinerU CLI failed: {result.stderr[:500]}"
            )

        # Find the output markdown file
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

        # Copy extracted images to persistent media dir
        img_src_dir = os.path.join(os.path.dirname(md_path), "images")
        img_map: Dict[str, str] = {}   # basename/relpath → absolute dest path

        if os.path.isdir(img_src_dir):
            import shutil
            for img_fname in os.listdir(img_src_dir):
                if not img_fname.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".webp", ".gif")
                ):
                    continue
                src  = os.path.join(img_src_dir, img_fname)
                dest = os.path.join(_MEDIA_DIR, img_fname)
                try:
                    shutil.copy2(src, dest)
                    # Map by multiple key formats MinerU might use
                    img_map[img_fname]                        = dest
                    img_map[f"images/{img_fname}"]            = dest
                    img_map[os.path.join("images", img_fname)]= dest
                except Exception as copy_err:
                    print(f"[WARN] Could not copy image {img_fname}: {copy_err}")

        sections, figures, tables = _parse_mineru_output(
            markdown, content_list, img_map
        )
        return markdown, sections, figures, tables
    
def _extract_caption(item: dict) -> str:
    """
    Extract caption text from a MinerU content_list item.
    MinerU uses several different caption formats depending on version:
      - image_caption: ["Figure 2. ..."]
      - image_caption: [{"type": "text", "text": "Figure 2. ..."}]
      - image_caption: [{"text": "Figure 2. ..."}]
      - img_caption: same variants
      - title: "Figure 2. ..."
      - Sometimes caption is in adjacent text blocks
    """
    # Try all known caption field names
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
                    # Try common text field names
                    for key in ("text", "content", "value", "c"):
                        if isinstance(p.get(key), str) and p[key].strip():
                            texts.append(p[key])
                            break
            result = " ".join(texts).strip()
            if result:
                return result

    # Fallback: check "title" field
    title = item.get("title", "")
    if isinstance(title, str) and title.strip():
        return title.strip()

    return ""    

def _enrich_captions_from_markdown(
    markdown: str,
    figures:  List[FigureModel],
) -> List[FigureModel]:
    """
    Enrich figure captions using three strategies:
    1. Inline markdown caption: ![caption](image.png)
    2. Text immediately after the image reference in markdown
    3. Search for 'Figure N.' patterns in markdown near the image

    Never overwrites existing captions.
    Never assigns wrong sequential numbers.
    """
    lines = markdown.splitlines()

    # Build a map of "Figure N" → caption text from the full markdown
    # This catches captions that appear as standalone text blocks
    figure_caption_map: dict[str, str] = {}
    for i, line in enumerate(lines):
        # Match patterns like "Figure 2.", "Figure 2:", "Fig. 2."
        m = re.match(
            r'^(Fig(?:ure)?\.?\s*\d+[A-Za-z]?)[\.:\s](.+)$',
            line.strip(),
            re.IGNORECASE,
        )
        if m:
            fig_ref = m.group(1).strip()
            caption = (m.group(1) + ". " + m.group(2)).strip()
            # Collect continuation lines
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("#") and not next_line.startswith("!"):
                    caption += " " + next_line
                else:
                    break
            figure_caption_map[fig_ref.lower()] = caption[:300]

    for fig in figures:
        if fig.caption:
            continue  # never overwrite

        img_fname = os.path.basename(fig.path) if fig.path else ""
        if not img_fname:
            continue

        # Strategy 1 & 2: look near the image reference in markdown
        for i, line in enumerate(lines):
            if img_fname not in line or not line.strip().startswith("!"):
                continue

            # Strategy 1: inline caption
            inline = re.match(r'!\[([^\]]+)\]', line)
            if inline and len(inline.group(1).strip()) > 5:
                fig.caption = inline.group(1).strip()
                break

            # Strategy 2: text immediately after
            for j in range(i + 1, min(i + 6, len(lines))):
                next_line = lines[j].strip()
                if (next_line
                        and not next_line.startswith("!")
                        and not next_line.startswith("#")
                        and len(next_line) > 10):
                    fig.caption = next_line[:200]
                    break
            if fig.caption:
                break

    # Strategy 3: for still-uncaptioned figures, try to match by page
    # to a "Figure N." caption found in the text
    # Sort figures by page to assign in order
    uncaptioned = [f for f in figures if not f.caption]
    if uncaptioned and figure_caption_map:
        # Sort caption map by figure number
        sorted_captions = sorted(
            figure_caption_map.items(),
            key=lambda x: int(re.search(r'\d+', x[0]).group())
            if re.search(r'\d+', x[0]) else 999,
        )
        # Assign by page order
        uncaptioned_sorted = sorted(uncaptioned, key=lambda f: f.page_idx)
        for fig, (_, caption) in zip(uncaptioned_sorted, sorted_captions):
            if not fig.caption:
                fig.caption = caption

    # Final fallback: page placeholder
    for fig in figures:
        if not fig.caption:
            fig.caption = f"Figure (page {fig.page_idx + 1})"

    return figures

def _parse_mineru_output(
    markdown:     str,
    content_list: list,
    img_map:      Dict[str, str],
) -> Tuple[List[SectionModel], List[FigureModel], List[TableModel]]:
    """
    Parse MinerU's markdown + content_list into structured models.
    This is the core of Phase 2B — turning raw output into
    queryable, agent-readable structure.
    """
    sections: List[SectionModel] = []
    figures:  List[FigureModel]  = []
    tables:   List[TableModel]   = []

    # ── Parse sections from markdown headings ─────────────────────────────────
    current_heading = "Introduction"
    current_level   = 2
    current_lines:  List[str] = []

    for line in markdown.splitlines():
        m = re.match(r'^(#{1,4})\s+(.+)$', line.strip())
        if m:
            # Save previous section
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

    # Save last section
    if current_lines:
        sections.append(SectionModel(
            heading=current_heading,
            level=current_level,
            content="\n".join(current_lines).strip(),
        ))

    # ── Parse figures and tables from content_list ────────────────────────────
    for item in content_list:
        item_type = item.get("type", "")
        page_idx  = item.get("page_idx", 0)

        if item_type in ("image", "figure"):
            # Handle all caption formats MinerU may produce
            caption = _extract_caption(item)

            img_path_rel = item.get("img_path", "")
            img_fname    = os.path.basename(img_path_rel)
            img_abs      = img_map.get(img_fname, "")

            # Also try the full relative path as key
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

    # ── Associate figures/tables to their nearest section ─────────────────────
    # Build a simple page→section map
    if sections and (figures or tables):
        # Assign each figure/table to the section whose content
        # mentions the figure number or is closest by page
        for fig in figures:
            fig.section = _find_section_for_caption(
                fig.caption, sections
            )
        for tbl in tables:
            tbl.section = _find_section_for_caption(
                tbl.caption, sections
            )
    # Enrich empty captions from markdown context
    if figures:
        figures = _enrich_captions_from_markdown(markdown, figures)

    return sections, figures, tables


def _find_section_for_caption(caption: str, sections: List[SectionModel]) -> str:
    """Find which section a figure/table caption belongs to."""
    if not caption:
        return ""
    cap_lower = caption.lower()
    # Look for figure/table number references in section content
    for s in sections:
        if cap_lower[:50] in s.content.lower():
            return s.heading
    return sections[-1].heading if sections else ""


# ── PyPDF2 fallback ───────────────────────────────────────────────────────────

def _extract_with_pypdf2(
    file_bytes: bytes,
) -> Tuple[str, List[SectionModel], List[FigureModel], List[TableModel]]:
    """
    Fallback extraction using PyPDF2.
    Produces minimal section structure from raw page text.
    No figures or tables extracted.
    """
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages  = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = " ".join(text.split())   # normalise whitespace
        pages.append(text)

    markdown = "\n\n".join(pages)

    # Build minimal sections — one per page
    sections = [
        SectionModel(
            heading=f"Page {i + 1}",
            level=2,
            content=page_text,
        )
        for i, page_text in enumerate(pages)
        if page_text.strip()
    ]

    return markdown, sections, [], []


# ── Public API ────────────────────────────────────────────────────────────────

def create_document(filename: str, file_bytes: bytes) -> DocumentModel:
    """
    Create a DocumentModel from uploaded PDF bytes.
    Tries MinerU first; falls back to PyPDF2 gracefully.
    """
    mineru_used = False
    try:
        if MINERU_AVAILABLE:
            markdown, sections, figures, tables = _extract_with_mineru(file_bytes)
            mineru_used = True
        else:
            markdown, sections, figures, tables = _extract_with_pypdf2(file_bytes)
    except Exception as e:
        print(f"[WARN] Primary extraction failed ({e}), falling back to PyPDF2")
        markdown, sections, figures, tables = _extract_with_pypdf2(file_bytes)
        mineru_used = False

    # Infer title
    title = filename
    for s in sections:
        if s.level == 1 and len(s.heading) > 5:
            title = s.heading
            break
    if title == filename:
        lines = [l.strip() for l in markdown.splitlines() if l.strip()]
        title = next((l[:300] for l in lines[:15] if len(l) > 20), filename)

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
        mineru_used=mineru_used,
    )
    DOCUMENTS[doc.document_id] = doc
    return doc


def get_document(document_id: str) -> DocumentModel:
    if document_id not in DOCUMENTS:
        raise KeyError(f"Unknown document_id: {document_id}")
    return DOCUMENTS[document_id]


def get_figure(figure_id: str) -> Optional[FigureModel]:
    """Find a figure by ID across all documents."""
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
    """
    Retrieve relevant passages for a query.

    With MinerU sections: searches headings first (exact → fuzzy → TF).
    Without sections: TF scoring on raw pages.

    The key improvement: "Case Study 2" matches the exact section heading
    rather than scoring raw text — deterministic, no false positives.
    """
    doc = get_document(document_id)

    if doc.sections:
        return _retrieve_from_sections(doc.sections, query, top_k, max_chars)
    else:
        return _retrieve_from_pages(doc.pages, query, top_k, max_chars)


def _retrieve_from_sections(
    sections:  List[SectionModel],
    query:     str,
    top_k:     int,
    max_chars: int,
) -> List[str]:
    """Section-aware retrieval with heading priority."""
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
    passages   = []
    for _, _, s in top:
        text    = f"## {s.heading}\n\n{s.content}"
        passages.append(text[:per_budget])
    return passages


def _retrieve_from_pages(
    pages:     List[str],
    query:     str,
    top_k:     int,
    max_chars: int,
) -> List[str]:
    """Fallback TF retrieval on raw pages."""
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
    """
    Return a compact chunk for summarisation.
    Prioritises abstract/introduction sections.
    """
    doc = get_document(document_id)

    if doc.sections:
        priority = {"abstract", "introduction", "overview", "summary", "background"}
        chunk    = ""
        for s in doc.sections[:6]:
            if any(kw in s.heading.lower() for kw in priority):
                chunk += f"## {s.heading}\n{s.content}\n\n"
                if len(chunk) >= max_chars:
                    break
        if not chunk:
            for s in doc.sections[:3]:
                chunk += f"## {s.heading}\n{s.content}\n\n"
                if len(chunk) >= max_chars:
                    break
        return chunk[:max_chars].strip()
    else:
        chunk = ""
        for page in doc.pages[:3]:
            if len(chunk) + len(page) > max_chars:
                chunk += page[:max_chars - len(chunk)]
                break
            chunk += page + "\n\n"
        return chunk.strip()


def get_figures_for_section(document_id: str, section_heading: str) -> List[FigureModel]:
    """Return all figures associated with a given section heading."""
    doc = get_document(document_id)
    return [f for f in doc.figures if f.section == section_heading]


def get_tables_for_section(document_id: str, section_heading: str) -> List[TableModel]:
    """Return all tables associated with a given section heading."""
    doc = get_document(document_id)
    return [t for t in doc.tables if t.section == section_heading]