import { useMaestroStore } from "@/store/maestroStore";
import { RotateCcw, Loader2, Sun, Moon } from "lucide-react";

export function TopBar() {
  const state     = useMaestroStore((s) => s.state);
  const reset     = useMaestroStore((s) => s.reset);
  const isLoading = useMaestroStore((s) => s.isLoading);
  const bgActive  = state?.background_job_active ?? false;
  const awaiting  = state?.awaiting_confirmation ?? false;

  const statusLabel = bgActive
    ? (state?.background_job_label ?? "Running workflow...")
    : awaiting
    ? "Awaiting your approval"
    : isLoading
    ? "Thinking..."
    : null;

  const statusColor = bgActive
    ? "text-blue-600"
    : awaiting
    ? "text-amber-600"
    : "text-blue-600";

  return (
    <header className="h-[60px] flex items-center justify-between px-6 bg-white border-b border-slate-200 shrink-0">

      <div className="flex items-center gap-2 min-w-0">
        {statusLabel ? (
          <div className={`flex items-center gap-2 text-sm font-medium ${statusColor}`}>
            {(bgActive || isLoading)
              ? <Loader2 size={14} className="animate-spin shrink-0" />
              : <span className="status-dot active" />}
            <span className="truncate">{statusLabel}</span>
          </div>
        ) : (
          <div className="h-5" />
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 text-red-400 hover:border-red-400 hover:text-red-600 text-xs font-medium transition-colors disabled:opacity-40"
        >
          <RotateCcw size={12} /> Reset
        </button>
      </div>
    </header>
  );
}