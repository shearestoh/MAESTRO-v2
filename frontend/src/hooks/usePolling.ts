import { useEffect, useRef } from "react";
import { useMaestroStore } from "@/store/maestroStore";

export function usePolling(intervalMs = 1000) {
  const bgActive    = useMaestroStore((s) => s.state?.background_job_active);
  const wsConnected = useMaestroStore((s) => s.wsConnected);
  const refreshState= useMaestroStore((s) => s.refreshState);
  const timerRef    = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Only poll when WebSocket is down AND a job is running
    if (!wsConnected && bgActive) {
      timerRef.current = setInterval(refreshState, intervalMs);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [wsConnected, bgActive, refreshState, intervalMs]);
}