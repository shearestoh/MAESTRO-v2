from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import websocket_endpoint
from app.core.tool_registry import register_default_tools

app = FastAPI(
    title="MAESTRO v3 API",
    description="Domain-agnostic agentic scientific orchestration",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register default virtual tools on startup
# These can be modified/extended via the Lab Builder
@app.on_event("startup")
def startup():
    register_default_tools()

app.include_router(router)

@app.websocket("/ws/{session_id}")
async def ws_route(websocket: WebSocket, session_id: str):
    await websocket_endpoint(websocket, session_id)