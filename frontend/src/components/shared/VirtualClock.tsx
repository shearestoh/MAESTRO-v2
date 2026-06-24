import { useMaestroStore } from "@/store/maestroStore";
import { formatVirtualTime } from "@/lib/utils";
import { Clock, Calendar } from "lucide-react";

const LAB_TOTAL = 480;

export function VirtualClock() {
  const state = useMaestroStore((s) => s.state);
  if (!state) return null;

  const { virtual_clock_minutes: mins, virtual_day_index: day } = state;
  const pct       = Math.min(100, (mins / LAB_TOTAL) * 100);
  const remaining = Math.max(0, LAB_TOTAL - mins);
  const barColor  = pct > 87.5
    ? "bg-red-500"
    : pct > 75
    ? "bg-amber-500"
    : "bg-blue-500";

  return (
    <div className="glass-panel p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-slate-400 text-xs uppercase tracking-wider font-semibold">
          <Calendar size={11} />
          Lab Time
        </div>
        <div className="flex items-center gap-1 text-slate-500 text-xs">
          <Clock size={10} />
          Day {day}
        </div>
      </div>

      <div className="text-3xl font-mono font-bold text-slate-100">
        {formatVirtualTime(mins)}
      </div>

      <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="flex justify-between text-xs text-slate-500">
        <span>09:00</span>
        <span>{remaining}m left</span>
        <span>17:00</span>
      </div>
    </div>
  );
}