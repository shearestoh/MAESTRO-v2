import { useEffect, useRef, useState } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { ProjectedScheduleEntry, ResourceLogEntry } from "@/types";

const panelHeaderCls = "text-sm font-semibold text-slate-700";

const INSTRUMENT_CONFIG: Record<string, { label: string; colour_actual: string; colour_proj: string }> = {
  sampler: { label: "Synthesis",        colour_actual: "bg-cyan-500",   colour_proj: "bg-cyan-200"   },
  tester:  { label: "Characterisation", colour_actual: "bg-yellow-500", colour_proj: "bg-yellow-200" },
};

function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return isoString;
  }
}

function formatDateTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleString([], {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

export function ResourceSchedule() {
  const state     = useMaestroStore((s) => s.state);
  const bgActive  = useMaestroStore((s) => s.state?.background_job_active ?? false);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!state) return null;

  const { resource_log, projected_schedule } = state;

  const hour = now.getHours();
  const isOfficeHours = hour >= 9 && hour < 17;

  const actualEntries: ResourceLogEntry[] = resource_log ?? [];
  const projEntries: ProjectedScheduleEntry[] = projected_schedule ?? [];

  const activeInstruments = ["sampler", "tester"].filter((inst) => {
    const hasActual    = actualEntries.some((e) => e.instrument === inst);
    const hasProjected = projEntries.some((e) => e.instrument_id === inst);
    return hasActual || hasProjected;
  });
  const rows = activeInstruments.length > 0 ? activeInstruments : ["sampler", "tester"];

  // Compute timeline bounds from actual entries
  const allTimes = actualEntries.flatMap((e) => [
    new Date(e.start_time).getTime(),
    new Date(e.end_time).getTime(),
  ]).filter(Boolean);

  const timelineStart = allTimes.length > 0
    ? new Date(Math.min(...allTimes) - 60_000)
    : new Date(now.getTime() - 5 * 60_000);
  const timelineEnd = new Date(Math.max(
    now.getTime() + 5 * 60_000,
    allTimes.length > 0 ? Math.max(...allTimes) + 60_000 : now.getTime() + 5 * 60_000,
  ));

  const totalMs = timelineEnd.getTime() - timelineStart.getTime();

  function pct(isoString: string): number {
    const t = new Date(isoString).getTime();
    return Math.max(0, Math.min(100, ((t - timelineStart.getTime()) / totalMs) * 100));
  }

  const nowPct = Math.max(0, Math.min(100,
    ((now.getTime() - timelineStart.getTime()) / totalMs) * 100
  ));

  return (
    <div className="glass-panel p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className={panelHeaderCls}>Task schedule</h2>
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            isOfficeHours
              ? "bg-green-100 text-green-700"
              : "bg-amber-100 text-amber-700"
          }`}>
            {isOfficeHours ? "Office hours" : "Out of hours"}
          </span>
          <span className="text-sm font-mono font-bold text-slate-800">
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      {/* Gantt rows */}
      <div className="space-y-2 overflow-x-auto">
        {rows.map((inst) => {
          const cfg      = INSTRUMENT_CONFIG[inst];
          const actBars  = actualEntries.filter((e) => e.instrument === inst);
          const projBars = projEntries.filter((e) => e.instrument_id === inst && e.is_projected);

          return (
            <div key={inst} className="flex items-center gap-2 min-w-0">
              <div className="text-[10px] text-slate-500 w-24 shrink-0 text-right">
                {cfg?.label ?? inst}
              </div>
              <div className="flex-1 h-5 bg-slate-100 rounded-full overflow-hidden relative min-w-[200px]">
                {/* Now cursor */}
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-red-400 z-20"
                  style={{ left: `${nowPct}%` }}
                />

                {/* Actual bars */}
                {actBars.map((e, i) => {
                  const left  = pct(e.start_time);
                  const right = pct(e.end_time);
                  const width = Math.max(0.5, right - left);
                  return (
                    <div
                      key={`actual-${i}`}
                      className={`absolute top-0.5 bottom-0.5 ${cfg?.colour_actual ?? "bg-slate-500"} rounded z-10`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={`${formatTime(e.start_time)} – ${formatTime(e.end_time)}`}
                    />
                  );
                })}

                {/* Projected bars */}
                {projBars.map((e, i) => (
                  <div
                    key={`proj-${i}`}
                    className={`absolute top-0.5 bottom-0.5 ${cfg?.colour_proj ?? "bg-slate-200"} rounded opacity-70 z-5`}
                    style={{
                      left:  `${Math.max(0, nowPct)}%`,
                      width: `${Math.min(100 - nowPct, 10)}%`,
                      backgroundImage: "repeating-linear-gradient(90deg, transparent, transparent 3px, rgba(255,255,255,0.5) 3px, rgba(255,255,255,0.5) 6px)",
                    }}
                    title={e.label}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-slate-400">
        <div className="flex items-center gap-1">
          <div className="w-4 h-2 bg-slate-400 rounded" />
          <span>Actual</span>
        </div>
        <div className="flex items-center gap-1">
          <div
            className="w-4 h-2 bg-slate-300 rounded"
            style={{ backgroundImage: "repeating-linear-gradient(90deg, transparent, transparent 2px, rgba(255,255,255,0.6) 2px, rgba(255,255,255,0.6) 4px)" }}
          />
          <span>Projected</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-0.5 h-3 bg-red-400" />
          <span>Now</span>
        </div>
      </div>

      {/* Timeline labels */}
      <div className="flex justify-between text-[10px] text-slate-400">
        <span>{formatDateTime(timelineStart.toISOString())}</span>
        <span>{formatDateTime(timelineEnd.toISOString())}</span>
      </div>

      {/* Recent activity log */}
      {actualEntries.length > 0 && (
        <div className="border-t border-slate-100 pt-2 space-y-1">
          <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Recent activity</div>
          {[...actualEntries].reverse().slice(0, 5).map((e, i) => (
            <div key={i} className="flex justify-between text-[10px] text-slate-500">
              <span>{e.instrument}</span>
              <span>{formatTime(e.start_time)} – {formatTime(e.end_time)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}