import { useMaestroStore } from "@/store/maestroStore";
import { RotateCcw, Sun } from "lucide-react";

export function TopBar() {
  const state     = useMaestroStore((s) => s.state);
  const nextDay   = useMaestroStore((s) => s.nextDay);
  const reset     = useMaestroStore((s) => s.reset);
  const isLoading = useMaestroStore((s) => s.isLoading);
  const bgActive  = state?.background_job_active ?? false;

  return (
    <header className="h-[72px] flex items-center justify-between px-6 bg-slate-900 border-b border-slate-700 shrink-0">
      <div className="flex flex-col">
        <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">
          Current Mission
        </div>
        <div className="text-sm text-slate-200 font-medium max-w-xl truncate">
          {state?.current_mission ?? "Awaiting scientific instruction."}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {bgActive && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-medium">
            <span className="status-dot active" />
            {state?.background_job_label ?? "Running"}
          </div>
        )}

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