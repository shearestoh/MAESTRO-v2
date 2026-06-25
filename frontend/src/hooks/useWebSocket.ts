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

        // Only push displayable events to the feed
        // Filter out system heartbeats from the visible log
        if (event.event_type !== "state_update") {
          pushWsEvent(event);
        }

        // Refresh state on every state_update
        // (now fires after every individual lab event)
        if (event.event_type === "state_update") {
          refreshState();

          // Extra refresh when job finishes
          const payload = event.payload as Record<string, unknown>;
          if (payload.background_job_active === false &&
              payload.background_job_status === "completed") {
            setTimeout(() => refreshState(), 500);
          }
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