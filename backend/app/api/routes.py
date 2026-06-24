"""All REST API routes — clean, thin handlers that delegate to orchestrator."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.artifacts import (
    export_campaign_json_bytes, export_results_csv_bytes,
    export_results_json_bytes, save_bytes_to_tempfile,
)
from app.core.documents import create_document, get_document
from app.core.extraction import extract_case_study_to_campaign
from app.core.models import (
    ConfirmRequest, CreateSessionResponse, NextDayRequest,
    ResetRequest, StateResponse, UserMessageRequest,
)
from app.core.orchestrator import (
    confirm_pending, create_session, get_session, next_day,
    post_user_message, register_artifact, reset_session, session_state_payload,
)
from app.core.skills import describe_extracted_campaign, summarise_uploaded_document

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "MAESTRO v3"}


@router.post("/session", response_model=CreateSessionResponse)
def create_session_route():
    return CreateSessionResponse(session_id=create_session().session_id)


@router.get("/state/{session_id}", response_model=StateResponse)
def get_state_route(session_id: str):
    try:
        session = get_session(session_id)
        return StateResponse(session_id=session_id, state=session_state_payload(session))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/message", response_model=StateResponse)
def message_route(req: UserMessageRequest):
    try:
        session = post_user_message(req.session_id, req.text)
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/confirm", response_model=StateResponse)
def confirm_route(req: ConfirmRequest):
    try:
        session = confirm_pending(req.session_id, req.proceed)
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/next-day", response_model=StateResponse)
def next_day_route(req: NextDayRequest):
    try:
        session = next_day(req.session_id)
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/reset", response_model=StateResponse)
def reset_route(req: ResetRequest):
    try:
        session = reset_session(req.session_id)
        return StateResponse(session_id=req.session_id, state=session_state_payload(session))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/documents/upload")
async def upload_document(session_id: str = Form(...), file: UploadFile = File(...)):
    try:
        session = get_session(session_id)
        session.equipment_status.knowledge = True
        session.current_activity = "Reading paper..."
        file_bytes = await file.read()
        doc = create_document(file.filename, file_bytes)
        doc.summary = summarise_uploaded_document(doc)
        session.active_document_id = doc.document_id
        session.current_mission    = f"Paper: {doc.filename}"
        session.agent_state.messages.append({
            "role": "assistant",
            "content": doc.summary or f"Paper **{doc.filename}** ingested.",
        })
        session.equipment_status.knowledge = False
        session.current_activity = None
        return {"status": "ok", "document_id": doc.document_id, "state": session_state_payload(session)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/documents/{document_id}/extract-case-study")
def extract_case_study_route(document_id: str, session_id: str = Form(...), case_name: str = Form(...)):
    try:
        session = get_session(session_id)
        session.equipment_status.knowledge = True
        session.current_activity = "Extracting case study..."
        extraction = extract_case_study_to_campaign(document_id, case_name)
        session.extracted_campaign = extraction.campaign
        session.active_document_id = document_id
        session.current_mission    = f"Reproduce: {extraction.campaign.target_case_study}"
        session.agent_state.messages.append({
            "role": "assistant",
            "content": describe_extracted_campaign(extraction.campaign),
        })
        session.equipment_status.knowledge = False
        session.current_activity = None
        return {"status": "ok", "extraction": extraction.model_dump(), "state": session_state_payload(session)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


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
        return FileResponse(path, media_type="application/json", filename="maestro_results.json")
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/export/campaign-json/{session_id}")
def export_campaign(session_id: str):
    try:
        session = get_session(session_id)
        data    = export_campaign_json_bytes(
            session.extracted_campaign.model_dump() if session.extracted_campaign else None
        )
        path    = save_bytes_to_tempfile(data, ".json", "maestro_campaign_")
        register_artifact(session, "campaign.json", "json", path)
        return FileResponse(path, media_type="application/json", filename="maestro_campaign.json")
    except KeyError as e:
        raise HTTPException(404, str(e))