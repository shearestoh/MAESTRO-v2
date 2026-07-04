import { useEffect, useState } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { ProjectedScheduleEntry, ResourceLogEntry } from "@/types";

const sectionHeaderCls = "text-sm font-semibold text-slate-700";

function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

function formatDateTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleString([], {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

// Zoom levels in seconds (not minutes) for fine-grained control
const ZOOM_LEVELS_SECONDS = [30, 60, 300, 600, 1800, 3600, 14400, 86400];
const ZOOM_LABELS         = ["30s", "1m", "5m", "10m", "30m", "1h", "4h", "24h"];

export function ResourceSchedule() {
  const state = useMaestroStore((s) => s.state);

  const [now, setNow]                     = useState(new Date());
  const [zoomIdx, setZoomIdx]             = useState(3);   // default: 10-minute window
  const [scrollOffsetMs, setScrollOffsetMs] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!state) return null;

  const { resource_log, projected_schedule } = state;
  const actualEntries: ResourceLogEntry[]       = resource_log ?? [];
  const projEntries:   ProjectedScheduleEntry[] = projected_schedule ?? [];

  const hour     = now.getHours();
  const isOffice = hour >= 9 && hour < 17;

  const windowMs = ZOOM_LEVELS_SECONDS[zoomIdx] * 1000;

  // Constrain scroll: "Now" must always be visible.
  // scrollOffsetMs > 0 means we're looking into the future (now moves left).
  // scrollOffsetMs < 0 means we're looking into the past (now moves right).
  // Constraint: now must be at least at 10% from left (i.e. scrollOffsetMs <= windowMs * 0.9)
  // and at most at 100% from left (i.e. scrollOffsetMs >= 0, now is always visible)
  // Actually: allow scrolling left (past) freely, but cap right scroll so now stays visible.
  const maxScrollRight = windowMs * 0.85;  // now can be at most 85% from left
  const clampedOffset  = Math.min(scrollOffsetMs, maxScrollRight);

  // viewStart: the time at the left edge of the Gantt
  // When offset=0: now is at 50% (centered)
  // When offset>0: we scrolled right (future), now moves left
  // When offset<0: we scrolled left (past), now moves right
  const viewStart = new Date(now.getTime() - windowMs / 2 + clampedOffset);
  const viewEnd   = new Date(viewStart.getTime() + windowMs);

  function pct(isoString: string): number {
    const t = new Date(isoString).getTime();
    return ((t - viewStart.getTime()) / windowMs) * 100;
  }

  const nowPct = ((now.getTime() - viewStart.getTime()) / windowMs) * 100;

  // Collect instrument rows: always show registered physical instruments
  // plus any that appear in actual/projected logs
  const registeredInstruments: string[] = [];
  // We'll get these from the resource log and projected schedule
  const loggedInstruments = new Set([
    ...actualEntries.map((e) => e.instrument),
    ...projEntries.map((e) => e.instrument_name).filter((n): n is string => Boolean(n)),
  ]);

  const filteredInstruments = Array.from(loggedInstruments).filter(
    (n) => n && !["unknown", "memory", "reporting", "knowledge", "optimiser", ""].includes(n)
  );

  // If no activity yet, show placeholder rows based on what we know from the registry
  // We can infer from the projected schedule what instruments exist
  const rows = filteredInstruments.length > 0 ? filteredInstruments : [];

  const palette = [
    { actual: "bg-cyan-500",   proj: "bg-cyan-200"   },
    { actual: "bg-yellow-500", proj: "bg-yellow-200" },
    { actual: "bg-violet-500", proj: "bg-violet-200" },
    { actual: "bg-green-500",  proj: "bg-green-200"  },
    { actual: "bg-orange-500", proj: "bg-orange-200" },
  ];

  const COLOURS: Record<string, { actual: string; proj: string }> = {};
  rows.forEach((name, i) => {
    COLOURS[name] = palette[i % palette.length];
  });

  const zoomIn  = () => setZoomIdx((z) => Math.max(0, z - 1));
  const zoomOut = () => setZoomIdx((z) => Math.min(ZOOM_LEVELS_SECONDS.length - 1, z + 1));

  const scrollLeft = () => {
    setScrollOffsetMs((o) => o - windowMs / 4);
  };

  const scrollRight = () => {
    setScrollOffsetMs((o) => {
      const next = o + windowMs / 4;
      return Math.min(next, maxScrollRight);
    });
  };

  const resetView = () => setScrollOffsetMs(0);

  const isScrolled = Math.abs(scrollOffsetMs) > 100;

  return (
    <div className="glass-panel p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className={sectionHeaderCls}>Task schedule</h2>
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            isOffice ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
          }`}>
            {isOffice ? "Office hours" : "Out of hours"}
          </span>
          <span className="text-sm font-mono font-bold text-slate-800">
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      {/* Zoom & scroll controls */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={scrollLeft}
          className="px-2 py-1 rounded text-xs text-slate-500 hover:bg-slate-100 transition-colors"
          title="Scroll to past"
        >
          ‹
        </button>
        <button
          onClick={zoomIn}
          className="px-2 py-1 rounded text-xs text-slate-500 hover:bg-slate-100 transition-colors"
          title="Zoom in (shorter window)"
        >
          +
        </button>
        <span className="text-[10px] text-slate-400 font-mono w-10 text-center">
          {ZOOM_LABELS[zoomIdx]}
        </span>
        <button
          onClick={zoomOut}
          className="px-2 py-1 rounded text-xs text-slate-500 hover:bg-slate-100 transition-colors"
          title="Zoom out (longer window)"
        >
          −
        </button>
        <button
          onClick={scrollRight}
          className="px-2 py-1 rounded text-xs text-slate-500 hover:bg-slate-100 transition-colors"
          title="Scroll to future"
        >
          ›
        </button>
        {isScrolled && (
          <button
            onClick={resetView}
            className="px-2 py-1 rounded text-[10px] text-blue-500 hover:bg-blue-50 transition-colors ml-1"
            title="Return to now"
          >
            ● Now
          </button>
        )}
      </div>

      {/* Gantt rows */}
      <div className="space-y-2">
        {rows.length === 0 ? (
          <div className="text-xs text-slate-400 italic py-2">
            No instrument activity yet. Tasks will appear here when workflows run.
          </div>
        ) : (
          rows.map((instName) => {
            const cfg      = COLOURS[instName] ?? palette[0];
            const actBars  = actualEntries.filter((e) => e.instrument === instName);
            const projBars = projEntries.filter(
              (e) => e.instrument_name === instName && e.is_projected
            );

            return (
              <div key={instName} className="flex items-center gap-2">
                <div
                  className="text-[10px] text-slate-500 w-28 shrink-0 text-right truncate"
                  title={instName}
                >
                  {instName}
                </div>
                <div className="flex-1 h-5 bg-slate-100 rounded overflow-hidden relative">
                  {/* Now cursor — always visible within the bar */}
                  {nowPct >= 0 && nowPct <= 100 && (
                    <div
                      className="absolute top-0 bottom-0 w-0.5 bg-red-400 z-20"
                      style={{ left: `${nowPct}%` }}
                    />
                  )}

                  {/* Actual bars */}
                  {actBars.map((e, i) => {
                    const left  = pct(e.start_time);
                    const right = pct(e.end_time);
                    const width = Math.max(1, right - left);  // min 1% so short tasks are visible
                    if (right < 0 || left > 100) return null;
                    const durationMs = new Date(e.end_time).getTime() - new Date(e.start_time).getTime();
                    const durationS  = (durationMs / 1000).toFixed(1);
                    return (
                      <div
                        key={`actual-${i}`}
                        className={`absolute top-0.5 bottom-0.5 ${cfg.actual} rounded z-10 cursor-pointer group`}
                        style={{
                          left:  `${Math.max(0, left)}%`,
                          width: `${Math.min(width, 100 - Math.max(0, left))}%`,
                        }}
                        title={`${instName}: ${formatTime(e.start_time)} – ${formatTime(e.end_time)} (${durationS}s)`}
                      >
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-30 pointer-events-none">
                          <div className="bg-slate-800 text-white text-[9px] rounded px-1.5 py-0.5 whitespace-nowrap shadow">
                            {formatTime(e.start_time)} – {formatTime(e.end_time)} ({durationS}s)
                          </div>
                        </div>
                      </div>
                    );
                  })}

                  {/* Projected bars */}
                  {projBars.map((e, i) => {
                    const left  = pct(e.start_time);
                    const right = pct(e.end_time);
                    const width = Math.max(1, right - left);
                    if (right < 0 || left > 100) return null;
                    return (
                      <div
                        key={`proj-${i}`}
                        className={`absolute top-0.5 bottom-0.5 ${cfg.proj} rounded opacity-70 z-5`}
                        style={{
                          left:  `${Math.max(0, left)}%`,
                          width: `${Math.min(width, 100 - Math.max(0, left))}%`,
                          backgroundImage: "repeating-linear-gradient(90deg, transparent, transparent 3px, rgba(255,255,255,0.5) 3px, rgba(255,255,255,0.5) 6px)",
                        }}
                        title={`Projected: ${e.label}`}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
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
        <span>{formatDateTime(viewStart.toISOString())}</span>
        <span>{formatDateTime(viewEnd.toISOString())}</span>
      </div>

      {/* Recent activity log */}
      {actualEntries.length > 0 && (
        <div className="border-t border-slate-100 pt-2 space-y-1 max-h-24 overflow-y-auto">
          <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider sticky top-0 bg-white">
            Recent activity
          </div>
          {[...actualEntries].reverse().slice(0, 10).map((e, i) => {
            const durationMs = new Date(e.end_time).getTime() - new Date(e.start_time).getTime();
            const durationS  = (durationMs / 1000).toFixed(1);
            return (
              <div key={i} className="flex justify-between text-[10px] text-slate-500">
                <span className="truncate max-w-[120px]">{e.instrument}</span>
                <span className="font-mono text-slate-400">
                  {formatTime(e.start_time)} ({durationS}s)
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}