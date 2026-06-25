"""
WebSocket endpoint — streams live agent events to the browser.

Key design:
- Drains ALL queued events per tick (not capped at 5)
- Sends state_update after EVERY event so frontend refreshes
  equipment status immediately — this is what makes nodes glow
- Covers: document upload, LLM calls, background BO jobs
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
            # ── Drain ALL queued events ───────────────────────────────────────
            events_sent = 0
            while session.live_event_queue:
                event = session.live_event_queue[0]
                try:
                    # Send the lab event
                    await websocket.send_text(json.dumps({
                        "event_type": event.event_type,
                        "message":    event.message,
                        "equipment":  event.equipment,
                        "category":   event.category,
                        "payload":    event.payload,
                    }))
                    session.live_event_queue.pop(0)
                    events_sent += 1

                    # Send a state_update immediately after EACH event
                    # This is what triggers frontend to call refreshState()
                    # which reads equipment_status and lights up the node
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
                        },
                    }))

                    # Small yield between events so browser can process each one
                    await asyncio.sleep(0.08)

                except Exception:
                    break

            # ── Heartbeat when background job is running ──────────────────────
            current_status = session.background_job_status
            job_active     = session.background_job_active

            if job_active and events_sent == 0:
                # Only send heartbeat if no events were just sent
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
                        },
                    }))
                except Exception:
                    break

            # ── Final notification when job completes ─────────────────────────
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