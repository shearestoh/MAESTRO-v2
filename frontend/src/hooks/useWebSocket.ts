import { useEffect, useRef, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

const BASE_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY  = 30000;
const MAX_RECONNECTS       = 12;

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
    const host     = window.location.host;
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

        if (event.event_type !== "state_update") {
          pushWsEvent(event);
        }

        if (event.event_type === "state_update") {
          refreshState();
          const payload = event.payload as Record<string, unknown>;
          if (payload.job_complete === true) {
            refreshState();
            setTimeout(() => refreshState(), 300);
            setTimeout(() => refreshState(), 800);
          }
          if (
            payload.background_job_active === false &&
            payload.background_job_status === "completed"
          ) {
            setTimeout(() => refreshState(), 500);
          }
        }

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