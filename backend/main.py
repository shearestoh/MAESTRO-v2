from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import websocket_endpoint
from app.core.tool_registry import register_default_instruments
from app.core.lab_config import load_lab_settings, load_library_documents_into_store
from app.core.database import ensure_db

app = FastAPI(
    title="MAESTRO API",
    description="Materials Acceleration Engine for Synthesis, Testing and Orchestration",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    settings = load_lab_settings()
    print(f"[INFO] Lab: {settings.lab_name}")
    ensure_db()
    register_default_instruments()
    load_library_documents_into_store()
    try:
        import mineru
        print("[INFO] MinerU available")
    except ImportError:
        print("[WARN] MinerU not installed. Install with: pip install mineru")


app.include_router(router)


@app.websocket("/ws/{session_id}")
async def ws_route(websocket: WebSocket, session_id: str):
    await websocket_endpoint(websocket, session_id)