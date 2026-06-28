import { useMaestroStore } from "@/store/maestroStore";
import { RotateCcw, Loader2, Sun, Moon } from "lucide-react";

export function TopBar() {
  const state       = useMaestroStore((s) => s.state);
  const reset       = useMaestroStore((s) => s.reset);
  const isLoading   = useMaestroStore((s) => s.isLoading);
  const theme       = useMaestroStore((s) => s.theme);
  const toggleTheme = useMaestroStore((s) => s.toggleTheme);
  const bgActive    = state?.background_job_active ?? false;
  const awaiting    = state?.awaiting_confirmation ?? false;

  const statusLabel = bgActive
    ? (state?.background_job_label ?? "Running workflow...")
    : awaiting
    ? "Awaiting your approval"
    : isLoading
    ? "Thinking..."
    : null;

  const statusColor = bgActive
    ? "text-blue-600 dark:text-blue-400"
    : awaiting
    ? "text-amber-600 dark:text-amber-400"
    : "text-blue-600 dark:text-blue-400";

  return (
    <header className="h-[60px] flex items-center justify-between px-6 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 shrink-0">

      {/* Status — only when active */}
      <div className="flex items-center gap-2 min-w-0">
        {statusLabel ? (
          <div className={`flex items-center gap-2 text-sm font-medium ${statusColor}`}>
            {(bgActive || isLoading) ? (
              <Loader2 size={14} className="animate-spin shrink-0" />
            ) : (
              <span className="status-dot active" />
            )}
            <span className="truncate">{statusLabel}</span>
          </div>
        ) : (
          <div className="h-5" />
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
        >
          {theme === "light"
            ? <Moon size={15} />
            : <Sun  size={15} />}
        </button>

        {/* Reset */}
        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 dark:border-red-500/30 text-red-400 dark:text-red-400/70 hover:border-red-400 dark:hover:border-red-500/60 hover:text-red-600 dark:hover:text-red-400 text-xs font-medium transition-colors disabled:opacity-40"
        >
          <RotateCcw size={12} /> Reset
        </button>
      </div>
    </header>
  );
}