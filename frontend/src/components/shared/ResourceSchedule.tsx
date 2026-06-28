import { useMaestroStore } from "@/store/maestroStore";
import { formatVirtualTime } from "@/lib/utils";

const LAB_TOTAL = 480; // 09:00 → 17:00

// Memory removed — instantaneous operation, not meaningful on Gantt
const TOOL_COLOURS: Record<string, string> = {
  sampler:   "bg-cyan-500",
  tester:    "bg-yellow-500",
  optimiser: "bg-violet-500",
};

const TOOL_LABELS: Record<string, string> = {
  sampler:   "Sampler",
  tester:    "Tester",
  optimiser: "Optimiser",
};

export function ResourceSchedule() {
  const state   = useMaestroStore((s) => s.state);
  const nextDay = useMaestroStore((s) => s.nextDay);
  const bgActive= useMaestroStore((s) => s.state?.background_job_active ?? false);
  const isLoading = useMaestroStore((s) => s.isLoading);

  if (!state) return null;

  const {
    virtual_clock_minutes: mins,
    virtual_day_index:     day,
    resource_log,
  } = state;

  const pct       = Math.min(100, (mins / LAB_TOTAL) * 100);
  const remaining = Math.max(0, LAB_TOTAL - mins);

  // Filter log to current day only
  const todayLog = (resource_log ?? []).filter((e) => e.day === day);

  // Only sampler, tester, optimiser on Gantt (memory removed)
  const tools = ["sampler", "tester", "optimiser"];

  return (
    <div className="glass-panel p-4 space-y-3">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Lab Resources
        </div>
        <div className="text-xs text-slate-500">Day {day}</div>
      </div>

      {/* Current time */}
      <div className="flex items-center justify-between">
        <div className="text-2xl font-mono font-bold text-slate-100">
          {formatVirtualTime(mins)}
        </div>
        {/* Next Day button — moved here from TopBar */}
        <button
          onClick={nextDay}
          disabled={bgActive || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:border-blue-500 hover:text-blue-400 text-xs font-medium transition-colors disabled:opacity-40"
        >
          Next Day →
        </button>
      </div>

      {/* Gantt rows — memory removed */}
      <div className="space-y-1.5">
        {tools.map((tool) => {
          const entries = todayLog.filter((e) => e.tool === tool);
          return (
            <div key={tool} className="flex items-center gap-2">
              <div className="text-[10px] text-slate-500 w-16 shrink-0 text-right">
                {TOOL_LABELS[tool]}
              </div>
              <div className="flex-1 h-3 bg-slate-800 rounded-full overflow-hidden relative">
                {/* Current time cursor */}
                <div
                  className="absolute top-0 bottom-0 w-px bg-slate-500 z-10"
                  style={{ left: `${pct}%` }}
                />
                {/* Usage blocks */}
                {entries.map((e, i) => {
                  const left  = (e.start_min / LAB_TOTAL) * 100;
                  const width = ((e.end_min - e.start_min) / LAB_TOTAL) * 100;
                  return (
                    <div
                      key={i}
                      className={`absolute top-0 bottom-0 ${TOOL_COLOURS[tool] ?? "bg-slate-500"} opacity-80`}
                      style={{
                        left:  `${left}%`,
                        width: `${Math.max(0.5, width)}%`,
                      }}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="flex justify-between text-[10px] text-slate-600">
        <span>09:00</span>
        <span className={remaining < 60 ? "text-red-400" : "text-slate-500"}>
          {remaining}m remaining
        </span>
        <span>17:00</span>
      </div>
    </div>
  );
}