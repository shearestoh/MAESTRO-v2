import { useEffect, useRef, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

const BASE_RECONNECT_DELAY = 1_000;
const MAX_RECONNECT_DELAY  = 30_000;
const MAX_RECONNECTS       = 12;

// Events that should trigger a state refresh
const REFRESH_EVENT_TYPES = new Set([
  "job_complete",
  "optimiser_complete",
  "synthesiser_done",
  "characteriser_done",
  "memory_update",
  "feasibility_result",
  "knowledge_done",
  "plotter_done",
  "analysis_done",
]);

export function useWebSocket() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const pushWsEvent  = useMaestroStore((s) => s.pushWsEvent);
  const setConnected = useMaestroStore((s) => s.setWsConnected);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const wsRef      = useRef<WebSocket | null>(null);
  const reconnects = useRef(0);
  const timerRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted    = useRef(true);

  const connect = useCallback(() => {
    if (!sessionId || !mounted.current) return;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url      = `${protocol}://${window.location.host}/ws/${sessionId}`;
    const ws       = new WebSocket(url);
    wsRef.current  = ws;

    ws.onopen = () => {
      reconnects.current = 0;
      setConnected(true);
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as WsEvent;

        // Silently ignore ping keepalives
        if (event.event_type === "ping") return;

        if (event.event_type === "state_update") {
          const payload = event.payload as Record<string, unknown>;
          if (payload.job_complete === true) {
            refreshState();
            setTimeout(() => refreshState(), 400);
          } else if (
            payload.background_job_active === false &&
            payload.background_job_status === "completed"
          ) {
            setTimeout(() => refreshState(), 500);
          }
          return;
        }

        pushWsEvent(event);

        if (REFRESH_EVENT_TYPES.has(event.event_type)) {
          refreshState();
        }
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (!mounted.current) return;
      if (reconnects.current < MAX_RECONNECTS) {
        const delay = Math.min(
          BASE_RECONNECT_DELAY * Math.pow(2, reconnects.current),
          MAX_RECONNECT_DELAY,
        );
        reconnects.current += 1;
        timerRef.current = setTimeout(connect, delay);
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