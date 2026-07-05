import { useEffect, useRef, useState, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { ProjectedScheduleEntry, ResourceLogEntry } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return iso; }
}

function formatAxisLabel(date: Date, windowMs: number): string {
  if (windowMs <= 120_000) {
    // < 2 min: show HH:MM:SS
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  if (windowMs <= 7_200_000) {
    // < 2 hours: show HH:MM
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  // > 2 hours: show date + HH:MM
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Zoom levels in milliseconds
const ZOOM_LEVELS_MS = [
  30_000,       // 30s
  60_000,       // 1m
  300_000,      // 5m
  600_000,      // 10m
  1_800_000,    // 30m
  3_600_000,    // 1h
  14_400_000,   // 4h
  86_400_000,   // 24h
];
const ZOOM_LABELS = ["30s", "1m", "5m", "10m", "30m", "1h", "4h", "24h"];
const DEFAULT_ZOOM_IDX = 3; // 10m

interface TooltipState {
  x: number;
  y: number;
  text: string;
}

// ── Known physical instruments (fallback when registry not in frontend state) ──
// These are always shown as rows even before any tasks run.
const ALWAYS_SHOW_INSTRUMENTS = ["Electrode Coater", "Potentiostat"];

// ── Main Component ────────────────────────────────────────────────────────────

export function ResourceSchedule() {
  const state = useMaestroStore((s) => s.state);

  // ── Viewport state (absolute epoch ms) ──────────────────────────────────────
  // viewStartMs is the absolute time at the LEFT edge of the Gantt.
  // This NEVER auto-resets. The "Now" line moves across it.
  const [viewStartMs, setViewStartMs] = useState<number>(() => {
    // Initial view: show last 2.5 minutes on left, next 7.5 minutes on right (10m window)
    const windowMs = ZOOM_LEVELS_MS[DEFAULT_ZOOM_IDX];
    return Date.now() - windowMs * 0.25;
  });
  const [zoomIdx,  setZoomIdx]  = useState(DEFAULT_ZOOM_IDX);
  const [tooltip,  setTooltip]  = useState<TooltipState | null>(null);
  const [now,      setNow]      = useState(Date.now());

  const ganttRef    = useRef<HTMLDivElement>(null);
  const isDragging  = useRef(false);
  const dragStartX  = useRef(0);
  const dragStartViewMs = useRef(0);

  // Live clock — only updates `now`, never touches viewport
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const windowMs   = ZOOM_LEVELS_MS[zoomIdx];
  const viewEndMs  = viewStartMs + windowMs;
  const nowPct     = ((now - viewStartMs) / windowMs) * 100;

  // ── Scroll-wheel zoom (zoom around cursor position) ──────────────────────────
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const el = ganttRef.current;
    if (!el) return;

    const rect        = el.getBoundingClientRect();
    const cursorRatio = (e.clientX - rect.left) / rect.width; // 0..1
    const cursorTimeMs = viewStartMs + cursorRatio * windowMs;

    const delta    = e.deltaY > 0 ? 1 : -1;
    const newIdx   = Math.max(0, Math.min(ZOOM_LEVELS_MS.length - 1, zoomIdx + delta));
    const newWindowMs = ZOOM_LEVELS_MS[newIdx];

    // Keep cursor time fixed: newViewStart = cursorTime - cursorRatio * newWindow
    const newViewStart = cursorTimeMs - cursorRatio * newWindowMs;

    setZoomIdx(newIdx);
    setViewStartMs(newViewStart);
  }, [viewStartMs, windowMs, zoomIdx]);

  useEffect(() => {
    const el = ganttRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  // ── Click-drag to pan ────────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current    = true;
    dragStartX.current    = e.clientX;
    dragStartViewMs.current = viewStartMs;
    e.preventDefault();
  }, [viewStartMs]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current || !ganttRef.current) return;
    const rect       = ganttRef.current.getBoundingClientRect();
    const deltaX     = e.clientX - dragStartX.current;
    const deltaMs    = -(deltaX / rect.width) * windowMs;
    setViewStartMs(dragStartViewMs.current + deltaMs);
  }, [windowMs]);

  const handleMouseUp = useCallback(() => {
    isDragging.current = false;
  }, []);

  // ── Data ─────────────────────────────────────────────────────────────────────
  const actualEntries: ResourceLogEntry[]       = state?.resource_log        ?? [];
  const projEntries:   ProjectedScheduleEntry[] = state?.projected_schedule  ?? [];
  const bgActive = state?.background_job_active ?? false;

  // Collect instrument rows:
  // 1. Always show known physical instruments
  // 2. Add any instruments that appear in actual/projected logs
  const instrumentSet = new Set<string>(ALWAYS_SHOW_INSTRUMENTS);
  actualEntries.forEach((e) => {
    if (e.instrument && !["unknown", "memory", "reporting", "knowledge", "optimiser", ""].includes(e.instrument)) {
      instrumentSet.add(e.instrument);
    }
  });
  projEntries.forEach((e) => {
    if (e.instrument_name && !["unknown", "memory", "reporting", "knowledge", "optimiser", ""].includes(e.instrument_name)) {
      instrumentSet.add(e.instrument_name);
    }
  });
  const rows = Array.from(instrumentSet);

  // Colour palette per instrument
  const palette = [
    { actual: "#06b6d4", proj: "#a5f3fc" },  // cyan
    { actual: "#f59e0b", proj: "#fde68a" },  // amber
    { actual: "#8b5cf6", proj: "#ddd6fe" },  // violet
    { actual: "#22c55e", proj: "#bbf7d0" },  // green
    { actual: "#f97316", proj: "#fed7aa" },  // orange
  ];
  const COLOURS: Record<string, { actual: string; proj: string }> = {};
  rows.forEach((name, i) => { COLOURS[name] = palette[i % palette.length]; });

  // ── Axis tick marks ──────────────────────────────────────────────────────────
  function generateTicks(): { pct: number; label: string }[] {
    const tickCount = 6;
    const tickIntervalMs = windowMs / tickCount;
    const ticks = [];
    for (let i = 0; i <= tickCount; i++) {
      const tickMs  = viewStartMs + i * tickIntervalMs;
      const tickPct = (i / tickCount) * 100;
      ticks.push({ pct: tickPct, label: formatAxisLabel(new Date(tickMs), windowMs) });
    }
    return ticks;
  }
  const ticks = generateTicks();

  // ── Bar rendering helper ─────────────────────────────────────────────────────
  function pct(isoOrMs: string | number): number {
    const t = typeof isoOrMs === "string" ? new Date(isoOrMs).getTime() : isoOrMs;
    return ((t - viewStartMs) / windowMs) * 100;
  }

  function renderBar(
    key:         string,
    startIso:    string,
    endIso:      string,
    colour:      string,
    tooltipText: string,
    isProjected  = false,
  ) {
    const leftPct  = pct(startIso);
    const rightPct = pct(endIso);
    if (rightPct < 0 || leftPct > 100) return null;

    const clippedLeft  = Math.max(0, leftPct);
    const clippedRight = Math.min(100, rightPct);
    const widthPct     = Math.max(0.3, clippedRight - clippedLeft);

    return (
      <div
        key={key}
        className="absolute top-1 bottom-1 rounded"
        style={{
          left:            `${clippedLeft}%`,
          width:           `${widthPct}%`,
          backgroundColor: colour,
          opacity:         isProjected ? 0.5 : 1,
          backgroundImage: isProjected
            ? "repeating-linear-gradient(90deg, transparent, transparent 4px, rgba(255,255,255,0.4) 4px, rgba(255,255,255,0.4) 8px)"
            : undefined,
          cursor: "default",
        }}
        onMouseEnter={(ev) => setTooltip({ x: ev.clientX, y: ev.clientY, text: tooltipText })}
        onMouseLeave={() => setTooltip(null)}
        onMouseMove={(ev) => setTooltip({ x: ev.clientX, y: ev.clientY, text: tooltipText })}
      />
    );
  }

  // ── Scroll to show recent activity ──────────────────────────────────────────
  const jumpToNow = () => {
    // Show last 25% past, 75% future
    setViewStartMs(Date.now() - windowMs * 0.25);
  };

  const jumpToHistory = () => {
    // Show all actual bars: fit view to span from first to last bar + padding
    if (actualEntries.length === 0) return;
    const starts = actualEntries.map((e) => new Date(e.start_time).getTime());
    const ends   = actualEntries.map((e) => new Date(e.end_time).getTime());
    const earliest = Math.min(...starts);
    const latest   = Math.max(...ends, Date.now());
    const span     = latest - earliest;
    const padding  = span * 0.1;

    // Find smallest zoom that fits
    let bestZoom = ZOOM_LEVELS_MS.length - 1;
    for (let i = 0; i < ZOOM_LEVELS_MS.length; i++) {
      if (ZOOM_LEVELS_MS[i] >= span + padding * 2) {
        bestZoom = i;
        break;
      }
    }
    setZoomIdx(bestZoom);
    setViewStartMs(earliest - padding);
  };

  const isNearNow = Math.abs(nowPct - 25) < 5; // within 5% of default position

  // ── Hour of day ──────────────────────────────────────────────────────────────
  const hour     = new Date(now).getHours();
  const isOffice = hour >= 9 && hour < 17;

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="glass-panel p-4 space-y-2" style={{ position: "relative", userSelect: "none" }}>

      {/* Floating tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-slate-800 text-white text-[10px] rounded px-2 py-1 shadow-lg pointer-events-none whitespace-nowrap"
          style={{ left: tooltip.x + 12, top: tooltip.y - 32 }}
        >
          {tooltip.text}
        </div>
      )}

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-slate-700">Task schedule</h2>
          {bgActive && (
            <span className="text-[10px] text-blue-600 font-mono animate-pulse">● LIVE</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            isOffice ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
          }`}>
            {isOffice ? "Office hours" : "Out of hours"}
          </span>
          <span className="text-sm font-mono font-bold text-slate-800">
            {new Date(now).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      {/* ── Toolbar ── */}
      <div className="flex items-center gap-2 text-xs">
        <button
          onClick={jumpToNow}
          className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
            isNearNow
              ? "bg-blue-100 text-blue-600"
              : "bg-slate-100 text-slate-600 hover:bg-blue-50 hover:text-blue-600"
          }`}
          title="Jump to now"
        >
          ↩ Now
        </button>
        {actualEntries.length > 0 && (
          <button
            onClick={jumpToHistory}
            className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
            title="Fit view to all recorded tasks"
          >
            ⊡ Fit history
          </button>
        )}
        <span className="font-mono bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-[10px]">
          {ZOOM_LABELS[zoomIdx]} window
        </span>
        <span className="ml-auto text-[10px] text-slate-400">
          Scroll to zoom · Drag to pan
        </span>
      </div>

      {/* ── Gantt area ── */}
      <div
        ref={ganttRef}
        className="relative"
        style={{ cursor: isDragging.current ? "grabbing" : "grab" }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* Axis ticks */}
        <div className="relative h-5 mb-1 border-b border-slate-200">
          {ticks.map((tick, i) => (
            <div
              key={i}
              className="absolute top-0 flex flex-col items-center"
              style={{ left: `${tick.pct}%`, transform: "translateX(-50%)" }}
            >
              <div className="h-2 w-px bg-slate-300" />
              <span className="text-[9px] text-slate-400 whitespace-nowrap mt-0.5">
                {tick.label}
              </span>
            </div>
          ))}
          {/* Now marker on axis */}
          {nowPct >= 0 && nowPct <= 100 && (
            <div
              className="absolute top-0 bottom-0 flex flex-col items-center pointer-events-none"
              style={{ left: `${nowPct}%`, transform: "translateX(-50%)" }}
            >
              <div className="h-2 w-px bg-red-400" />
              <span className="text-[9px] text-red-400 font-semibold whitespace-nowrap mt-0.5">now</span>
            </div>
          )}
        </div>

        {/* Instrument rows */}
        <div className="space-y-1.5">
          {rows.map((instName) => {
            const cfg      = COLOURS[instName] ?? palette[0];
            const actBars  = actualEntries.filter((e) => e.instrument === instName);
            const projBars = projEntries.filter(
              (e) => e.instrument_name === instName && e.is_projected
            );

            return (
              <div key={instName} className="flex items-center gap-2">
                {/* Label */}
                <div
                  className="text-[10px] text-slate-500 font-medium shrink-0 text-right"
                  style={{ width: 120 }}
                  title={instName}
                >
                  {instName}
                </div>

                {/* Track */}
                <div
                  className="flex-1 relative rounded"
                  style={{ height: 20, backgroundColor: "#f1f5f9" }}
                >
                  {/* Vertical grid lines at tick positions */}
                  {ticks.map((tick, i) => (
                    <div
                      key={i}
                      className="absolute top-0 bottom-0 w-px bg-slate-200 pointer-events-none"
                      style={{ left: `${tick.pct}%` }}
                    />
                  ))}

                  {/* Now line */}
                  {nowPct >= 0 && nowPct <= 100 && (
                    <div
                      className="absolute top-0 bottom-0 w-0.5 bg-red-400 z-20 pointer-events-none"
                      style={{ left: `${nowPct}%` }}
                    />
                  )}

                  {/* Projected bars (behind actual) */}
                  {projBars.map((e, i) => {
                    const durationMs = new Date(e.end_time).getTime() - new Date(e.start_time).getTime();
                    const durationS  = (durationMs / 1000).toFixed(0);
                    return renderBar(
                      `proj-${instName}-${i}`,
                      e.start_time,
                      e.end_time,
                      cfg.proj,
                      `Projected: ${e.label} (${durationS}s)`,
                      true,
                    );
                  })}

                  {/* Actual bars (on top) */}
                  {actBars.map((e, i) => {
                    const durationMs = new Date(e.end_time).getTime() - new Date(e.start_time).getTime();
                    const durationS  = (durationMs / 1000).toFixed(1);
                    return renderBar(
                      `actual-${instName}-${i}`,
                      e.start_time,
                      e.end_time,
                      cfg.actual,
                      `${instName}: ${formatTime(e.start_time)} – ${formatTime(e.end_time)} (${durationS}s)`,
                      false,
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="flex items-center gap-4 text-[10px] text-slate-500 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-2.5 rounded" style={{ backgroundColor: "#06b6d4" }} />
          <span>Actual</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div
            className="w-5 h-2.5 rounded opacity-50"
            style={{
              backgroundColor: "#a5f3fc",
              backgroundImage: "repeating-linear-gradient(90deg, transparent, transparent 3px, rgba(255,255,255,0.5) 3px, rgba(255,255,255,0.5) 6px)",
            }}
          />
          <span>Projected</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-0.5 h-3 bg-red-400" />
          <span>Now</span>
        </div>
        {actualEntries.length > 0 && (
          <span className="ml-auto text-slate-400">
            {actualEntries.length} task{actualEntries.length !== 1 ? "s" : ""} recorded
          </span>
        )}
      </div>

      {/* ── Recent activity log ── */}
      {actualEntries.length > 0 && (
        <div className="border-t border-slate-100 pt-2">
          <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider mb-1.5">
            Recent activity
          </div>
          <div className="space-y-0.5 max-h-28 overflow-y-auto">
            {[...actualEntries].reverse().slice(0, 15).map((e, i) => {
              const durationMs = new Date(e.end_time).getTime() - new Date(e.start_time).getTime();
              const durationS  = (durationMs / 1000).toFixed(1);
              const cfg        = COLOURS[e.instrument] ?? palette[0];
              return (
                <div key={i} className="flex items-center justify-between text-[10px]">
                  <div className="flex items-center gap-1.5">
                    <div
                      className="w-2 h-2 rounded-sm shrink-0"
                      style={{ backgroundColor: cfg.actual }}
                    />
                    <span className="text-slate-600 font-medium truncate max-w-[120px]">
                      {e.instrument}
                    </span>
                  </div>
                  <span className="font-mono text-slate-400 shrink-0 ml-2">
                    {formatTime(e.start_time)} · {durationS}s
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}