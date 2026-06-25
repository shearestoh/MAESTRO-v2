import { useMaestroStore } from "@/store/maestroStore";
import { RotateCcw, Sun, Loader2 } from "lucide-react";

export function TopBar() {
  const state     = useMaestroStore((s) => s.state);
  const nextDay   = useMaestroStore((s) => s.nextDay);
  const reset     = useMaestroStore((s) => s.reset);
  const isLoading = useMaestroStore((s) => s.isLoading);
  const bgActive  = state?.background_job_active ?? false;
  const awaiting  = state?.awaiting_confirmation ?? false;

  // Determine agent status
  const statusLabel = bgActive
    ? (state?.background_job_label ?? "Running workflow...")
    : awaiting
    ? "Awaiting your approval"
    : isLoading
    ? "Thinking..."
    : "Idle — ready for instruction";

  const statusColor = bgActive
    ? "text-blue-400"
    : awaiting
    ? "text-amber-400"
    : isLoading
    ? "text-blue-400"
    : "text-slate-500";

  return (
    <header className="h-[60px] flex items-center justify-between px-6 bg-slate-900 border-b border-slate-700 shrink-0">
      {/* Agent status */}
      <div className={`flex items-center gap-2 text-sm font-medium ${statusColor}`}>
        {(bgActive || isLoading) ? (
          <Loader2 size={14} className="animate-spin shrink-0" />
        ) : (
          <span className={`status-dot ${bgActive || isLoading ? "active" : "idle"}`} />
        )}
        <span>{statusLabel}</span>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <button
          onClick={nextDay}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:border-blue-500 hover:text-blue-400 text-xs font-medium transition-colors disabled:opacity-40"
        >
          <Sun size={12} /> Next Day
        </button>
        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/40 text-red-400 hover:bg-red-500/10 text-xs font-medium transition-colors disabled:opacity-40"
        >
          <RotateCcw size={12} /> Reset
        </button>
      </div>
    </header>
  );
}