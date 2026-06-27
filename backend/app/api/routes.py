"""
All REST API routes — thin handlers delegating to orchestrator.
Phase 2A: Tool registry CRUD endpoints.
Phase 2B: /media/{figure_id} and /documents/{id}/structure endpoints.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.artifacts import (
    export_campaign_json_bytes,
    export_results_csv_bytes,
    export_results_json_bytes,
    save_bytes_to_tempfile,
)
from app.core.documents import create_document, get_document, get_figure
from app.core.extraction import extract_case_study_to_campaign
from app.core.models import (
    ConfirmRequest,
    CreateSessionResponse,
    ExecutionEvent, 
    NextDayRequest,
    ResetRequest,
    StateResponse,
    UserMessageRequest,
)
from app.core.orchestrator import (
    confirm_pending,
    create_session,
    get_session,
    next_day,
    post_user_message,
    register_artifact,
    reset_session,
    session_state_payload,
)
from app.core.skills import describe_extracted_campaign, summarise_uploaded_document
from app.core.tool_registry import TOOL_REGISTRY, VirtualTool

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {
        "status":      "ok",
        "service":     "MAESTRO v3",
        "tools_count": len(TOOL_REGISTRY.list_all()),
    }


# ── Session ───────────────────────────────────────────────────────────────────

@router.post("/session", response_model=CreateSessionResponse)
def create_session_route():
    return CreateSessionResponse(session_id=create_session().session_id)


@router.get("/state/{session_id}", response_model=StateResponse)
def get_state_route(session_id: str):
    try:
        session = get_session(session_id)
        return StateResponse(
            session_id=session_id,
            state=session_state_payload(session),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/message", response_model=StateResponse)
def message_route(req: UserMessageRequest):
    try:
        session = post_user_message(req.session_id, req.text)
        return StateResponse(
            session_id=req.session_id,
            state=session_state_payload(session),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/confirm", response_model=StateResponse)
def confirm_route(req: ConfirmRequest):
    try:
        session = confirm_pending(req.session_id, req.proceed)
        return StateResponse(
            session_id=req.session_id,
            state=session_state_payload(session),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/next-day", response_model=StateResponse)
def next_day_route(req: NextDayRequest):
    try:
        session = next_day(req.session_id)
        return StateResponse(
            session_id=req.session_id,
            state=session_state_payload(session),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/reset", response_model=StateResponse)
def reset_route(req: ResetRequest):
    try:
        session = reset_session(req.session_id)
        return StateResponse(
            session_id=req.session_id,
            state=session_state_payload(session),
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


# ── Documents ─────────────────────────────────────────────────────────────────

@router.post("/documents/upload")
async def upload_document(
    session_id: str = Form(...),
    file:       UploadFile = File(...),
):
    try:
        session = get_session(session_id)

        # Step 1 — signal start
        session.equipment_status.knowledge = True
        session.current_activity = f"Reading paper: {file.filename}..."
        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_read",
            message=f"Reading paper: {file.filename}...",
            equipment="knowledge",
            category="knowledge",
            payload={},
        ))
        # Yield to event loop so WebSocket can drain the queue
        await asyncio.sleep(0.05)

        file_bytes = await file.read()

        # Step 2 — parsing
        session.current_activity = "Parsing document structure..."
        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_parse",
            message="Parsing document structure...",
            equipment="knowledge",
            category="knowledge",
            payload={},
        ))
        await asyncio.sleep(0.05)

        # Run blocking MinerU parse in a thread pool
        # so the event loop stays free during parsing
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        doc  = await loop.run_in_executor(
            None, create_document, file.filename, file_bytes
        )

        # Step 3 — summarising
        session.current_activity = "Summarising paper content..."
        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_summarise",
            message="Summarising paper content...",
            equipment="knowledge",
            category="knowledge",
            payload={},
        ))
        await asyncio.sleep(0.05)

        # Run blocking LLM call in thread pool
        doc.summary = await loop.run_in_executor(
            None, summarise_uploaded_document, doc
        )

        session.active_document_id = doc.document_id
        session.current_mission    = f"Paper: {doc.filename}"

        # Step 4 — done
        parser_note  = " (parsed with MinerU)" if doc.mineru_used else ""
        section_note = (
            f" Found {len(doc.sections)} sections"
            f", {len(doc.figures)} figures"
            f", {len(doc.tables)} tables."
            if doc.sections else ""
        )

        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_done",
            message=(
                f"Paper loaded: {len(doc.sections)} sections, "
                f"{len(doc.figures)} figures, {len(doc.tables)} tables."
            ),
            equipment="knowledge",
            category="knowledge",
            payload={
                "sections": len(doc.sections),
                "figures":  len(doc.figures),
                "tables":   len(doc.tables),
            },
        ))
        await asyncio.sleep(0.05)

        session.agent_state.messages.append({
            "role":    "assistant",
            "content": (
                f"{doc.summary or f'Paper **{doc.filename}** ingested.'}"
                f"{parser_note}{section_note}\n\n"
                f"What would you like to do? I can:\n"
                f"- Summarise the paper in more detail\n"
                f"- Extract and check feasibility of a specific case study\n"
                f"- Reproduce a result (tell me which case study or figure)"
            ),
        })

        session.equipment_status.knowledge = False
        session.current_activity           = None

        return {
            "status":      "ok",
            "document_id": doc.document_id,
            "mineru_used": doc.mineru_used,
            "sections":    len(doc.sections),
            "figures":     len(doc.figures),
            "tables":      len(doc.tables),
            "state":       session_state_payload(session),
        }

    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/documents/{document_id}/structure")
def get_document_structure(document_id: str):
    """Return the full structure of a parsed document."""
    try:
        doc = get_document(document_id)
        return {
            "status":   "ok",
            "title":    doc.title,
            "sections": [s.model_dump() for s in doc.sections],
            "figures":  [f.model_dump() for f in doc.figures],
            "tables":   [t.model_dump() for t in doc.tables],
        }
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/documents/{document_id}/extract-case-study")
def extract_case_study_route(
    document_id: str,
    session_id:  str = Form(...),
    case_name:   str = Form(...),
):
    try:
        session = get_session(session_id)
        session.equipment_status.knowledge = True
        session.current_activity           = "Extracting case study..."

        extraction = extract_case_study_to_campaign(document_id, case_name)
        session.extracted_campaign = extraction.campaign
        session.active_document_id = document_id
        session.current_mission    = f"Reproduce: {extraction.campaign.target_case_study}"

        session.agent_state.messages.append({
            "role":    "assistant",
            "content": describe_extracted_campaign(extraction.campaign),
        })

        session.equipment_status.knowledge = False
        session.current_activity           = None

        return {
            "status":     "ok",
            "extraction": extraction.model_dump(),
            "state":      session_state_payload(session),
        }
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ── Media serving (Phase 2B) ──────────────────────────────────────────────────

@router.get("/media/{figure_id}")
def serve_figure(figure_id: str):
    """
    Serve an extracted figure image.
    The agent references these as /api/media/{figure_id} in chat responses.
    react-markdown renders them inline automatically.
    """
    fig = get_figure(figure_id)
    if fig is None:
        raise HTTPException(404, "Figure not found")
    if not os.path.exists(fig.path):
        raise HTTPException(404, "Figure file not found on disk")
    return FileResponse(fig.path, media_type="image/png")

@router.get("/media")
def list_media():
    """
    Debug endpoint — list all saved media files and their IDs.
    Call this to verify MinerU figure extraction worked correctly.
    GET http://localhost:8000/media
    """
    from app.core.documents import _MEDIA_DIR, DOCUMENTS

    saved_files = []
    if os.path.isdir(_MEDIA_DIR):
        saved_files = sorted(os.listdir(_MEDIA_DIR))

    figure_index = []
    for doc in DOCUMENTS.values():
        for fig in doc.figures:
            figure_index.append({
                "figure_id":   fig.figure_id,
                "document":    doc.filename,
                "caption":     fig.caption[:100] if fig.caption else "",
                "path":        fig.path,
                "path_exists": os.path.exists(fig.path) if fig.path else False,
                "served_url":  fig.served_url,
            })

    return {
        "media_dir":    _MEDIA_DIR,
        "saved_files":  saved_files,
        "figure_count": len(figure_index),
        "figures":      figure_index,
    }


# ── Tool registry CRUD (Phase 2A.5) ──────────────────────────────────────────

@router.get("/tools")
def list_tools():
    """Return all registered virtual tools."""
    return {"status": "ok", "tools": TOOL_REGISTRY.to_dict_list()}


@router.post("/tools")
def register_tool(tool_data: dict):
    """Register a new virtual tool from the Lab Builder."""
    try:
        tool = VirtualTool(**tool_data)
        TOOL_REGISTRY.register(tool)
        return {"status": "ok", "tool": tool.model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid tool definition: {e}")


@router.put("/tools/{tool_id}")
def update_tool(tool_id: str, updates: dict):
    """Update a tool's properties from the Lab Builder."""
    result = TOOL_REGISTRY.update(tool_id, updates)
    if result is None:
        raise HTTPException(404, f"Tool {tool_id} not found")
    return {"status": "ok", "tool": result.model_dump()}


@router.delete("/tools/{tool_id}")
def delete_tool(tool_id: str):
    """Remove a tool from the registry."""
    if not TOOL_REGISTRY.remove(tool_id):
        raise HTTPException(404, f"Tool {tool_id} not found")
    return {"status": "ok"}


@router.get("/tools/{tool_id}")
def get_tool(tool_id: str):
    tool = TOOL_REGISTRY.get(tool_id)
    if tool is None:
        raise HTTPException(404, f"Tool {tool_id} not found")
    return {"status": "ok", "tool": tool.model_dump()}

# ── Plot serving ──────────────────────────────────────────────────────────────

@router.get("/plot/{session_id}")
def serve_plot(session_id: str):
    """
    Serve the most recently generated summary plot for a session.
    The frontend polls this after the plotter job completes.
    """
    try:
        session = get_session(session_id)
    except KeyError as e:
        raise HTTPException(404, str(e))

    path = session.show_plotter_image
    if not path:
        raise HTTPException(404, "No plot generated yet for this session")
    if not os.path.exists(path):
        raise HTTPException(404, "Plot file not found on disk")

    return FileResponse(path, media_type="image/png")


# ── Exports ───────────────────────────────────────────────────────────────────

@router.post("/export/results-csv/{session_id}")
def export_csv(session_id: str):
    try:
        session = get_session(session_id)
        data    = export_results_csv_bytes(session.agent_state.results_store)
        path    = save_bytes_to_tempfile(data, ".csv", "maestro_")
        register_artifact(session, "results.csv", "csv", path)
        return FileResponse(path, media_type="text/csv", filename="maestro_results.csv")
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/export/results-json/{session_id}")
def export_json(session_id: str):
    try:
        session = get_session(session_id)
        data    = export_results_json_bytes(session.agent_state.results_store)
        path    = save_bytes_to_tempfile(data, ".json", "maestro_")
        register_artifact(session, "results.json", "json", path)
        return FileResponse(
            path, media_type="application/json", filename="maestro_results.json"
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/export/campaign-json/{session_id}")
def export_campaign(session_id: str):
    try:
        session = get_session(session_id)
        data    = export_campaign_json_bytes(
            session.extracted_campaign.model_dump()
            if session.extracted_campaign else None
        )
        path    = save_bytes_to_tempfile(data, ".json", "maestro_campaign_")
        register_artifact(session, "campaign.json", "json", path)
        return FileResponse(
            path, media_type="application/json", filename="maestro_campaign.json"
        )
    except KeyError as e:
        raise HTTPException(404, str(e))