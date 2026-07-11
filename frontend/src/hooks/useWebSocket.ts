import { useEffect, useRef, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

const BASE_RECONNECT_DELAY = 1_000;
const MAX_RECONNECT_DELAY  = 30_000;
const MAX_RECONNECTS       = 12;

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

  // Stable connect function — reads sessionId from ref to avoid stale closure
  const sessionIdRef = useRef(sessionId);
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const connect = useCallback(() => {
    const sid = sessionIdRef.current;
    if (!sid || !mounted.current) return;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url      = `${protocol}://${window.location.host}/ws/${sid}`;
    const ws       = new WebSocket(url);
    wsRef.current  = ws;

    ws.onopen = () => {
      reconnects.current = 0;
      setConnected(true);
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as WsEvent;

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
  }, [pushWsEvent, setConnected, refreshState]); // sessionId read via ref — no stale closure

  // Re-connect whenever sessionId becomes available or changes
  useEffect(() => {
    if (!sessionId) return;
    mounted.current = true;
    // Close any existing connection before opening a new one
    if (wsRef.current) {
      wsRef.current.onclose = null; // prevent reconnect loop on intentional close
      wsRef.current.close();
    }
    reconnects.current = 0;
    connect();
    return () => {
      mounted.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [sessionId, connect]);
}