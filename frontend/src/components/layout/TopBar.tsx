import { useMaestroStore } from "@/store/maestroStore";
import { RotateCcw, Sun, Loader2 } from "lucide-react";

export function TopBar() {
  const state     = useMaestroStore((s) => s.state);
  const reset     = useMaestroStore((s) => s.reset);
  const isLoading = useMaestroStore((s) => s.isLoading);
  const bgActive  = state?.background_job_active ?? false;
  const awaiting  = state?.awaiting_confirmation ?? false;

  // Only show status when something meaningful is happening
  const statusLabel = bgActive
    ? (state?.background_job_label ?? "Running workflow...")
    : awaiting
    ? "Awaiting your approval"
    : isLoading
    ? "Thinking..."
    : null;   // ← null = show nothing when idle

  const statusColor = bgActive
    ? "text-blue-400"
    : awaiting
    ? "text-amber-400"
    : "text-blue-400";

  return (
    <header className="h-[60px] flex items-center justify-between px-6 bg-slate-900 border-b border-slate-700 shrink-0">

      {/* Agent status — only visible when active */}
      <div className="flex items-center gap-2 min-w-0">
        {statusLabel ? (
          <div className={`flex items-center gap-2 text-sm font-medium ${statusColor}`}>
            {(bgActive || isLoading) ? (
              <Loader2 size={14} className="animate-spin shrink-0" />
            ) : (
              <span className={`status-dot ${awaiting ? "active" : "idle"}`} />
            )}
            <span className="truncate">{statusLabel}</span>
          </div>
        ) : (
          // Empty placeholder to keep layout stable
          <div className="h-5" />
        )}
      </div>

      {/* Controls — Reset only (Next Day moved to Lab Resources) */}
      <div className="flex items-center gap-2">
        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/30 text-red-400/70 hover:border-red-500/60 hover:text-red-400 text-xs font-medium transition-colors disabled:opacity-40"
        >
          <RotateCcw size={12} /> Reset
        </button>
      </div>
    </header>
  );
}