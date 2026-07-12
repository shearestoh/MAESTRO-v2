"""
REST API routes — thin handlers delegating to orchestrator and core services.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid as _uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.artifacts import (
    export_campaign_json_bytes,
    export_results_csv_bytes,
    export_results_json_bytes,
    save_bytes_to_tempfile,
)
from app.core.database import (
    delete_protocol,
    delete_resource,
    get_all_protocols,
    get_all_resources,
    update_protocol_notes,
    upsert_protocol,
    upsert_resource,
)
from app.core.documents import DOCUMENTS, create_document, get_document, get_figure
from app.core.extraction import extract_case_study_to_campaign
from app.core.lab_config import (
    add_document_to_library,
    get_document_library,
    get_lab_settings,
    remove_document_from_library,
    save_lab_settings,
    update_lab_settings,
)
from app.core.llm import call_llm
from app.core.models import (
    ConfirmRequest,
    CreateSessionResponse,
    ExecutePlanRequest,
    ExecutionEvent,
    OptimisationLibraryEntry,
    OptimiserConfig,
    ProtocolEntry,
    ResetRequest,
    StateResponse,
    UpdateOptimiserRequest,
    UserMessageRequest,
)
from app.core.orchestrator import (
    confirm_pending,
    create_session,
    execute_plan,
    get_session,
    post_user_message,
    register_artifact,
    reset_session,
    session_state_payload,
)
from app.core.tool_registry import TOOL_REGISTRY, VirtualInstrument

router = APIRouter(prefix="/api")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summarise_document(doc) -> str:
    from app.core.documents import get_document_summary_chunk
    chunk = get_document_summary_chunk(doc.document_id, max_chars=1500)
    msg   = call_llm(
        messages=[
            {
                "role": "system",
                "content": "Summarise scientific papers concisely in 2-3 sentences.",
            },
            {
                "role": "user",
                "content": (
                    f"Summarise this paper in 2-3 sentences. "
                    f"Note if it contains reproducible optimisation case studies.\n\n"
                    f"Title: {doc.title or doc.filename}\n\n"
                    f"{chunk}"
                ),
            },
        ],
        tools=None,
    )
    return (msg.content or "").strip()


def _describe_campaign(campaign) -> str:
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
            {"role": "system", "content": "Describe scientific campaign plans naturally and concisely."},
            {
                "role": "user",
                "content": (
                    f"Describe this campaign in 3-5 sentences covering:\n"
                    f"- The identified case study\n"
                    f"- Inferred variables and conditions\n"
                    f"- Whether the lab can reproduce it\n"
                    f"- That the workflow plan will be shown for approval\n\n"
                    f"Campaign:\n{json.dumps(compact, indent=2)}"
                ),
            },
        ],
        tools=None,
    )
    return (msg.content or "").strip()


def _get_session_or_404(session_id: str):
    try:
        return get_session(session_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok", "service": "MAESTRO", "instruments": len(TOOL_REGISTRY.list_all())}


# ── Session ───────────────────────────────────────────────────────────────────

@router.post("/session", response_model=CreateSessionResponse)
def create_session_route():
    return CreateSessionResponse(session_id=create_session().session_id)


@router.get("/state/{session_id}", response_model=StateResponse)
def get_state_route(session_id: str):
    session = _get_session_or_404(session_id)
    return StateResponse(session_id=session_id, state=session_state_payload(session))


@router.post("/message", response_model=StateResponse)
def message_route(req: UserMessageRequest):
    session = _get_session_or_404(req.session_id)
    session = post_user_message(req.session_id, req.text)
    return StateResponse(session_id=req.session_id, state=session_state_payload(session))


@router.post("/confirm", response_model=StateResponse)
def confirm_route(req: ConfirmRequest):
    _get_session_or_404(req.session_id)
    session = confirm_pending(req.session_id, req.proceed)
    return StateResponse(session_id=req.session_id, state=session_state_payload(session))


@router.post("/execute-plan", response_model=StateResponse)
def execute_plan_route(req: ExecutePlanRequest):
    _get_session_or_404(req.session_id)
    try:
        session = execute_plan(req.session_id, req.plan)
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/reset", response_model=StateResponse)
def reset_route(req: ResetRequest):
    _get_session_or_404(req.session_id)
    session = reset_session(req.session_id)
    return StateResponse(session_id=req.session_id, state=session_state_payload(session))


# ── Documents ─────────────────────────────────────────────────────────────────

@router.post("/documents/upload")
async def upload_document(
    session_id: str      = Form(...),
    doc_type:   str      = Form("paper"),
    file:       UploadFile = File(...),
):
    session = _get_session_or_404(session_id)

    def _emit(event_type: str, message: str):
        session.live_event_queue.append(ExecutionEvent(
            event_type=event_type, message=message,
            equipment="knowledge", category="knowledge", payload={},
        ))
        session.current_activity = message

    # Validate doc_type
    if doc_type not in ("paper", "manual"):
        doc_type = "paper"

    try:
        session.equipment_status.knowledge = True
        _emit("knowledge_read", f"Reading: {file.filename}...")
        await asyncio.sleep(0.05)

        file_bytes = await file.read()

        _emit("knowledge_parse", "Parsing document structure...")
        await asyncio.sleep(0.05)

        loop = asyncio.get_event_loop()
        new_doc_id = str(_uuid.uuid4())
        doc = await loop.run_in_executor(
            None, create_document, file.filename, file_bytes, new_doc_id
        )

        add_document_to_library(
            document_id=doc.document_id,
            filename=doc.filename,
            title=doc.title,
            summary=doc.summary,
            uploaded_at=datetime.utcnow().isoformat(),
            file_bytes=file_bytes,
            doc_type=doc_type,   # ← pass through the actual doc_type
        )

        _emit("knowledge_summarise", "Summarising content...")
        await asyncio.sleep(0.05)
        doc.summary = await loop.run_in_executor(None, _summarise_document, doc)

        session.active_document_id = doc.document_id
        session.current_mission    = f"{'Manual' if doc_type == 'manual' else 'Paper'}: {doc.filename}"

        meta_lines = []
        if doc.authors:
            authors_str = ", ".join(doc.authors[:5])
            if len(doc.authors) > 5:
                authors_str += " et al."
            meta_lines.append(f"\n- **Authors:** {authors_str}")
        if doc.year:
            meta_lines.append(f"\n- **Year:** {doc.year}")
        if doc.doi:
            meta_lines.append(f"\n- **DOI:** {doc.doi}")

        section_note = (
            f" Found {len(doc.sections)} sections, "
            f"{len(doc.figures)} figures, {len(doc.tables)} tables."
            if doc.sections else ""
        )

        type_label = "Equipment manual" if doc_type == "manual" else "Paper"
        if doc_type == "manual":
            followup = (
                f"What would you like to do? I can:\n"
                f"- Answer questions about operating limits, safety constraints, or procedures\n"
                f"- Extract parameter ranges for instrument configuration\n"
                f"- Reference this manual when proposing experimental parameters"
            )
        else:
            followup = (
                f"What would you like to do? I can:\n"
                f"- Summarise the paper in more detail\n"
                f"- Answer questions about authors, year, methods, or findings\n"
                f"- Extract and check feasibility of a specific case study\n"
                f"- Reproduce a result (tell me which case study or figure)"
            )

        session.live_event_queue.append(ExecutionEvent(
            event_type="knowledge_done",
            message=f"{type_label} loaded: {len(doc.sections)} sections, {len(doc.figures)} figures.",
            equipment="knowledge",
            category="knowledge",
            payload={"sections": len(doc.sections), "figures": len(doc.figures), "tables": len(doc.tables)},
        ))
        await asyncio.sleep(0.05)

        session.agent_state.messages.append({
            "role": "assistant",
            "content": (
                f"{doc.summary or f'**{doc.filename}** ingested.'}"
                f"{''.join(meta_lines)}"
                f" (parsed with MinerU){section_note}\n\n"
                f"{followup}"
            ),
        })

        session.equipment_status.knowledge = False
        session.current_activity           = None

        return {
            "status":      "ok",
            "document_id": doc.document_id,
            "doc_type":    doc_type,
            "sections":    len(doc.sections),
            "figures":     len(doc.figures),
            "tables":      len(doc.tables),
            "state":       session_state_payload(session),
        }

    except Exception as e:
        session.equipment_status.knowledge = False
        session.current_activity           = None
        raise HTTPException(500, f"{type(e).__name__}: {e}")

@router.get("/documents/{document_id}/structure")
def get_document_structure(document_id: str):
    try:
        doc = get_document(document_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {
        "status":   "ok",
        "title":    doc.title,
        "authors":  doc.authors,
        "year":     doc.year,
        "doi":      doc.doi,
        "journal":  doc.journal,
        "sections": [s.model_dump() for s in doc.sections],
        "figures":  [f.model_dump() for f in doc.figures],
        "tables":   [t.model_dump() for t in doc.tables],
    }


@router.post("/documents/{document_id}/extract-case-study")
def extract_case_study_route(
    document_id: str,
    session_id:  str = Form(...),
    case_name:   str = Form(...),
):
    session = _get_session_or_404(session_id)
    try:
        session.equipment_status.knowledge = True
        session.current_activity           = "Extracting case study..."

        extraction = extract_case_study_to_campaign(document_id, case_name)
        session.extracted_campaign = extraction.campaign
        session.active_document_id = document_id
        session.current_mission    = f"Reproduce: {extraction.campaign.target_case_study}"

        session.agent_state.messages.append({
            "role": "assistant",
            "content": _describe_campaign(extraction.campaign),
        })
        return {
            "status":     "ok",
            "extraction": extraction.model_dump(),
            "state":      session_state_payload(session),
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        session.equipment_status.knowledge = False
        session.current_activity           = None


# ── Media serving ─────────────────────────────────────────────────────────────

@router.get("/media/{figure_id}")
def serve_figure(figure_id: str):
    fig = get_figure(figure_id)
    if fig is None or not os.path.exists(fig.path):
        raise HTTPException(404, "Figure not found")
    return FileResponse(fig.path, media_type="image/png")


@router.get("/media")
def list_media():
    from app.core.documents import _MEDIA_DIR
    saved_files  = sorted(os.listdir(_MEDIA_DIR)) if os.path.isdir(_MEDIA_DIR) else []
    figure_index = [
        {
            "figure_id":   fig.figure_id,
            "document":    doc.filename,
            "caption":     fig.caption[:100] if fig.caption else "",
            "path":        fig.path,
            "path_exists": os.path.exists(fig.path) if fig.path else False,
            "served_url":  fig.served_url,
        }
        for doc in DOCUMENTS.values()
        for fig in doc.figures
    ]
    return {"media_dir": _MEDIA_DIR, "saved_files": saved_files, "figures": figure_index}


# ── Instrument registry ───────────────────────────────────────────────────────

@router.get("/tools")
def list_tools():
    return {"status": "ok", "tools": TOOL_REGISTRY.to_dict_list()}


@router.post("/tools")
def register_tool(tool_data: dict):
    try:
        tool = VirtualInstrument(**tool_data)
        TOOL_REGISTRY.register(tool)
        return {"status": "ok", "tool": tool.model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid tool definition: {e}")


@router.put("/tools/{tool_id}")
def update_tool(tool_id: str, updates: dict):
    result = TOOL_REGISTRY.update(tool_id, updates)
    if result is None:
        raise HTTPException(404, f"Tool {tool_id} not found")
    return {"status": "ok", "tool": result.model_dump()}


@router.delete("/tools/{tool_id}")
def delete_tool(tool_id: str):
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
    session = _get_session_or_404(session_id)
    path    = session.show_plotter_image
    if not path or not os.path.exists(path):
        raise HTTPException(404, "No plot available for this session")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ── Exports ───────────────────────────────────────────────────────────────────

@router.post("/export/results-csv/{session_id}")
def export_csv(session_id: str):
    session = _get_session_or_404(session_id)
    data    = export_results_csv_bytes(session.agent_state.results_store)
    path    = save_bytes_to_tempfile(data, ".csv", "maestro_")
    register_artifact(session, "results.csv", "csv", path)
    return FileResponse(path, media_type="text/csv", filename="maestro_results.csv")


@router.post("/export/results-json/{session_id}")
def export_json(session_id: str):
    session = _get_session_or_404(session_id)
    data    = export_results_json_bytes(session.agent_state.results_store)
    path    = save_bytes_to_tempfile(data, ".json", "maestro_")
    register_artifact(session, "results.json", "json", path)
    return FileResponse(path, media_type="application/json", filename="maestro_results.json")


@router.post("/export/campaign-json/{session_id}")
def export_campaign(session_id: str):
    session = _get_session_or_404(session_id)
    data    = export_campaign_json_bytes(
        session.extracted_campaign.model_dump() if session.extracted_campaign else None
    )
    path = save_bytes_to_tempfile(data, ".json", "maestro_campaign_")
    register_artifact(session, "campaign.json", "json", path)
    return FileResponse(path, media_type="application/json", filename="maestro_campaign.json")


# ── Lab Settings ──────────────────────────────────────────────────────────────

@router.get("/lab-settings")
def get_lab_settings_route():
    return {"status": "ok", "settings": get_lab_settings().model_dump()}


@router.put("/lab-settings")
def update_lab_settings_route(updates: dict):
    try:
        return {"status": "ok", "settings": update_lab_settings(updates).model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid settings: {e}")


# ── Document Library ──────────────────────────────────────────────────────────

@router.get("/library")
def list_library():
    return {"status": "ok", "documents": [d.model_dump() for d in get_document_library()]}


@router.delete("/library/{document_id}")
def remove_from_library(document_id: str):
    if not remove_document_from_library(document_id):
        raise HTTPException(404, f"Document {document_id} not found in library")
    DOCUMENTS.pop(document_id, None)
    return {"status": "ok"}


# ── Optimisation Library ──────────────────────────────────────────────────────

@router.get("/optimisation-library")
def list_optimisation_library():
    return {"status": "ok", "libraries": [lib.model_dump() for lib in get_lab_settings().optimisation_library]}


@router.post("/optimisation-library")
def add_to_optimisation_library(entry: dict):
    try:
        lib_entry = OptimisationLibraryEntry(**entry)
        settings  = get_lab_settings()
        settings.optimisation_library.append(lib_entry)
        save_lab_settings(settings)
        return {"status": "ok", "entry": lib_entry.model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid entry: {e}")


@router.delete("/optimisation-library/{lib_id}")
def remove_from_optimisation_library(lib_id: str):
    settings = get_lab_settings()
    original = len(settings.optimisation_library)
    settings.optimisation_library = [lib for lib in settings.optimisation_library if lib.lib_id != lib_id]
    if len(settings.optimisation_library) == original:
        raise HTTPException(404, f"Library entry {lib_id} not found")
    save_lab_settings(settings)
    return {"status": "ok"}


# ── Optimiser config ──────────────────────────────────────────────────────────

@router.post("/optimiser", response_model=StateResponse)
def update_session_optimiser(req: UpdateOptimiserRequest):
    session = _get_session_or_404(req.session_id)
    try:
        session.optimiser_config = OptimiserConfig(
            name=req.name,
            n_calls=req.n_calls,
            n_initial_points=req.n_initial_points,
        )
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Resource Inventory ────────────────────────────────────────────────────────

@router.get("/resources")
def list_resources():
    return {"status": "ok", "resources": get_all_resources()}


@router.post("/resources")
def add_resource(resource_data: dict):
    from app.core.models import LabResource
    try:
        resource = LabResource(**resource_data)
        upsert_resource(resource.model_dump())
        return {"status": "ok", "resource": resource.model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid resource: {e}")


@router.put("/resources/{resource_id}")
def update_resource(resource_id: str, updates: dict):
    resources = get_all_resources()
    existing  = next((r for r in resources if r["resource_id"] == resource_id), None)
    if not existing:
        raise HTTPException(404, f"Resource {resource_id} not found")
    existing.update(updates)
    upsert_resource(existing)
    return {"status": "ok", "resource": existing}


@router.delete("/resources/{resource_id}")
def delete_resource_route(resource_id: str):
    if not delete_resource(resource_id):
        raise HTTPException(404, f"Resource {resource_id} not found")
    return {"status": "ok"}


# ── Protocols ─────────────────────────────────────────────────────────────────

@router.get("/protocols")
def list_protocols():
    return {"status": "ok", "protocols": get_all_protocols()}


@router.post("/protocols")
def save_protocol(data: dict):
    try:
        data.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
        entry = ProtocolEntry(**data)
        upsert_protocol(entry.model_dump())
        return {"status": "ok", "protocol": entry.model_dump()}
    except Exception as e:
        raise HTTPException(400, f"Invalid protocol: {e}")


@router.put("/protocols/{protocol_id}")
def update_protocol(protocol_id: str, updates: dict):
    protocols = get_all_protocols()
    existing  = next((p for p in protocols if p["protocol_id"] == protocol_id), None)
    if not existing:
        raise HTTPException(404, f"Protocol {protocol_id} not found")

    single_field_updates = {"notes", "name", "description", "results_summary"}
    if len(updates) == 1 and next(iter(updates)) in single_field_updates:
        field = next(iter(updates))
        from app.core.database import update_protocol_field
        update_protocol_field(protocol_id, field, updates[field])
    else:
        existing.update(updates)
        upsert_protocol(existing)

    protocols = get_all_protocols()
    updated   = next((p for p in protocols if p["protocol_id"] == protocol_id), None)
    if not updated:
        raise HTTPException(404, f"Protocol {protocol_id} not found after update")
    return {"status": "ok", "protocol": updated}


@router.delete("/protocols/{protocol_id}")
def delete_protocol_route(protocol_id: str):
    if not delete_protocol(protocol_id):
        raise HTTPException(404, f"Protocol {protocol_id} not found")
    return {"status": "ok"}