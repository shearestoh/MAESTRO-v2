from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import websocket_endpoint
from app.core.database import ensure_db
from app.core.lab_config import load_lab_settings, load_library_documents_into_store
from app.core.tool_registry import register_default_instruments


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_lab_settings()
    print(f"[INFO] Lab: {settings.lab_name}")
    ensure_db()
    register_default_instruments()

    try:
        import mineru  # noqa: F401
        print("[INFO] MinerU available — document parsing enabled")
        # Load library documents in background to avoid blocking startup
        import asyncio
        asyncio.get_event_loop().run_in_executor(None, load_library_documents_into_store)
    except ImportError:
        print(
            "[WARN] MinerU not installed — document upload/parsing disabled. "
            "Install with: pip install mineru[core]"
        )

    yield


_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]

app = FastAPI(
    title="MAESTRO API",
    description="Materials Acceleration Platform for Synthesis, Testing and Orchestration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.websocket("/ws/{session_id}")
async def ws_route(websocket: WebSocket, session_id: str):
    await websocket_endpoint(websocket, session_id)