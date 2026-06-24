"""
WebSocket endpoint — streams live agent events to the browser.

Why WebSocket instead of polling?
- Polling: browser asks "anything new?" every 800ms → wasteful, laggy
- WebSocket: server PUSHES events the instant they happen → smooth, real-time

The live_event_queue in each session is filled by the background job thread.
This endpoint drains it and sends each event to the connected browser.
"""
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from app.core.orchestrator import get_session


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    try:
        session = get_session(session_id)
    except KeyError:
        await websocket.close(code=4004, reason="Unknown session")
        return

    try:
        while True:
            # Drain any queued events and push them immediately
            drained = 0
            while session.live_event_queue and drained < 5:
                event = session.live_event_queue[0]
                try:
                    await websocket.send_text(json.dumps({
                        "event_type": event.event_type,
                        "message":    event.message,
                        "equipment":  event.equipment,
                        "category":   event.category,
                        "payload":    event.payload,
                    }))
                    session.live_event_queue.pop(0)
                    drained += 1
                except Exception:
                    break

            # Send a lightweight heartbeat when a job is running
            # so the frontend knows to refresh state
            if session.background_job_active or session.agent_state.awaiting_confirmation:
                try:
                    await websocket.send_text(json.dumps({
                        "event_type": "state_update",
                        "message":    session.current_activity or "Working...",
                        "equipment":  None,
                        "category":   "system",
                        "payload": {
                            "background_job_index":  session.background_job_index,
                            "background_job_status": session.background_job_status,
                            "background_job_active": session.background_job_active,
                        },
                    }))
                except Exception:
                    break

            await asyncio.sleep(0.15)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass