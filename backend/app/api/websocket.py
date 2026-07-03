"""
WebSocket endpoint — streams live agent events to the browser.
Drains all queued events per tick and sends a state_update after each.
"""
from __future__ import annotations

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

    last_job_status = None

    try:
        while True:
            events_sent = 0
            while session.live_event_queue:
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
                    events_sent += 1

                    await websocket.send_text(json.dumps({
                        "event_type": "state_update",
                        "message":    event.message,
                        "equipment":  None,
                        "category":   "system",
                        "payload": {
                            "background_job_active": session.background_job_active,
                            "background_job_status": session.background_job_status,
                            "background_job_index":  session.background_job_index,
                            "triggered_by":          event.event_type,
                            "job_complete":          event.event_type == "job_complete",
                        },
                    }))

                    await asyncio.sleep(0.08)

                except Exception:
                    break

            current_status = session.background_job_status
            job_active     = session.background_job_active

            if job_active and events_sent == 0:
                try:
                    await websocket.send_text(json.dumps({
                        "event_type": "state_update",
                        "message":    session.current_activity or "Working...",
                        "equipment":  None,
                        "category":   "system",
                        "payload": {
                            "background_job_active": True,
                            "background_job_index":  session.background_job_index,
                            "background_job_status": current_status,
                            "job_complete":          False,
                        },
                    }))
                except Exception:
                    break

            elif (
                not job_active
                and current_status != last_job_status
                and current_status in ("completed", "failed")
            ):
                try:
                    await websocket.send_text(json.dumps({
                        "event_type": "state_update",
                        "message":    "Job finished",
                        "equipment":  None,
                        "category":   "system",
                        "payload": {
                            "background_job_active": False,
                            "background_job_status": current_status,
                            "job_complete":          True,
                        },
                    }))
                    last_job_status = current_status
                except Exception:
                    break

            await asyncio.sleep(0.15)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass