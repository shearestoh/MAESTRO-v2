import { useEffect, useRef, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

const RECONNECT_DELAY = 2500;
const MAX_RECONNECTS  = 10;

export function useWebSocket() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const pushWsEvent  = useMaestroStore((s) => s.pushWsEvent);
  const setConnected = useMaestroStore((s) => s.setWsConnected);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const wsRef        = useRef<WebSocket | null>(null);
  const reconnects   = useRef(0);
  const timerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted      = useRef(true);

  const connect = useCallback(() => {
    if (!sessionId || !mounted.current) return;

    // Build WS URL — works with the Vite proxy
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const host     = window.location.host; // e.g. localhost:3000
    const url      = `${protocol}://${host}/ws/${sessionId}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnects.current = 0;
      setConnected(true);
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as WsEvent;

        // Push all non-heartbeat events to the visible feed
        if (event.event_type !== "state_update") {
          pushWsEvent(event);
        }

        // Refresh on state_update (fires after every lab event)
        if (event.event_type === "state_update") {
          refreshState();
          const payload = event.payload as Record<string, unknown>;
          if (
            payload.background_job_active === false &&
            payload.background_job_status === "completed"
          ) {
            setTimeout(() => refreshState(), 500);
          }
        }

        // ALSO refresh immediately on any equipment event
        // This is the belt-and-braces fix for node lighting:
        // state_update fires 80ms after the equipment event,
        // by which time equipment_status may already be reset.
        // Refreshing on the equipment event itself catches it while still True.
        if (event.equipment !== null && event.equipment !== undefined) {
          refreshState();
        }

      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (!mounted.current) return;
      if (reconnects.current < MAX_RECONNECTS) {
        reconnects.current += 1;
        timerRef.current = setTimeout(connect, RECONNECT_DELAY);
      }
    };

    ws.onerror = () => ws.close();
  }, [sessionId, pushWsEvent, setConnected, refreshState]);

  useEffect(() => {
    mounted.current = true;
    connect();
    return () => {
      mounted.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);
}