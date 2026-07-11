import { useEffect, useRef, useState, useCallback } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import type { ProjectedScheduleEntry, ResourceLogEntry } from "@/types";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return iso; }
}

function formatAxisLabel(date: Date, windowMs: number): string {
  if (windowMs <= 120_000)   return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (windowMs <= 7_200_000) return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const ZOOM_LEVELS_MS = [30_000, 60_000, 300_000, 600_000, 1_800_000, 3_600_000, 14_400_000, 86_400_000];
const ZOOM_LABELS    = ["30s", "1m", "5m", "10m", "30m", "1h", "4h", "24h"];
const DEFAULT_ZOOM   = 3;
const LABEL_WIDTH_PX = 128;

interface Tooltip { x: number; y: number; text: string; }

export function ResourceSchedule() {
  const state = useMaestroStore((s) => s.state);

  const [viewStartMs, setViewStartMs] = useState<number>(() =>
    Date.now() - ZOOM_LEVELS_MS[DEFAULT_ZOOM] * 0.25
  );
  const [zoomIdx,    setZoomIdx]    = useState(DEFAULT_ZOOM);
  const [tooltip,    setTooltip]    = useState<Tooltip | null>(null);
  const [now,        setNow]        = useState(Date.now());
  const [isDragging, setIsDragging] = useState(false);

  const trackAreaRef  = useRef<HTMLDivElement>(null);
  const dragStartX    = useRef(0);
  const dragStartView = useRef(0);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const windowMs  = ZOOM_LEVELS_MS[zoomIdx];
  const viewEndMs = viewStartMs + windowMs;

  const pct = useCallback((isoOrMs: string | number): number => {
    const t = typeof isoOrMs === "string" ? new Date(isoOrMs).getTime() : isoOrMs;
    return ((t - viewStartMs) / windowMs) * 100;
  }, [viewStartMs, windowMs]);

  const nowPct = pct(now);

  // Stable refs for wheel handler
  const viewStartMsRef = useRef(viewStartMs);
  const windowMsRef    = useRef(windowMs);
  const zoomIdxRef     = useRef(zoomIdx);
  useEffect(() => { viewStartMsRef.current = viewStartMs; }, [viewStartMs]);
  useEffect(() => { windowMsRef.current    = windowMs;    }, [windowMs]);
  useEffect(() => { zoomIdxRef.current     = zoomIdx;     }, [zoomIdx]);

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const el = trackAreaRef.current;
    if (!el) return;
    const rect        = el.getBoundingClientRect();
    const cursorRatio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const cursorMs    = viewStartMsRef.current + cursorRatio * windowMsRef.current;
    const newIdx      = Math.max(0, Math.min(ZOOM_LEVELS_MS.length - 1, zoomIdxRef.current + (e.deltaY > 0 ? 1 : -1)));
    const newWindowMs = ZOOM_LEVELS_MS[newIdx];
    setZoomIdx(newIdx);
    setViewStartMs(cursorMs - cursorRatio * newWindowMs);
  }, []);

  useEffect(() => {
    const el = trackAreaRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    dragStartX.current    = e.clientX;
    dragStartView.current = viewStartMs;
    e.preventDefault();
  }, [viewStartMs]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !trackAreaRef.current) return;
    const rect    = trackAreaRef.current.getBoundingClientRect();
    const deltaMs = -((e.clientX - dragStartX.current) / rect.width) * windowMs;
    setViewStartMs(dragStartView.current + deltaMs);
  }, [isDragging, windowMs]);

  const onMouseUp = useCallback(() => setIsDragging(false), []);

  const actualEntries: ResourceLogEntry[]       = state?.resource_log       ?? [];
  const projEntries:   ProjectedScheduleEntry[] = state?.projected_schedule ?? [];
  const bgActive = state?.background_job_active ?? false;

  const instruments = useMaestroStore((s) => s.instruments);
  const physicalInstrumentNames = instruments
    .filter((i) => i.category === "physical")
    .map((i) => i.name);

  const instrumentSet = new Set<string>(physicalInstrumentNames);
  const skipInstruments = new Set(["unknown", "memory", "reporting", "knowledge", "optimiser", ""]);
  actualEntries.forEach((e) => { if (e.instrument && !skipInstruments.has(e.instrument)) instrumentSet.add(e.instrument); });
  projEntries.forEach((e)   => { if (e.instrument_name && !skipInstruments.has(e.instrument_name)) instrumentSet.add(e.instrument_name); });
  const rows = Array.from(instrumentSet);

  const palette = [
    { actual: "#06b6d4", proj: "#a5f3fc" },
    { actual: "#f59e0b", proj: "#fde68a" },
    { actual: "#8b5cf6", proj: "#ddd6fe" },
    { actual: "#22c55e", proj: "#bbf7d0" },
    { actual: "#f97316", proj: "#fed7aa" },
  ];
  const COLOURS: Record<string, { actual: string; proj: string }> = {};
  rows.forEach((name, i) => { COLOURS[name] = palette[i % palette.length]; });

  const TICK_COUNT = 6;
  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => ({
    pct:   (i / TICK_COUNT) * 100,
    label: formatAxisLabel(new Date(viewStartMs + (i / TICK_COUNT) * windowMs), windowMs),
  }));

  function renderBar(
    key:        string,
    startIso:   string,
    endIso:     string,
    colour:     string,
    tipText:    string,
    isProjected = false,
  ) {
    const lp = pct(startIso);
    const rp = pct(endIso);
    if (rp < 0 || lp > 100) return null;
    const cl = Math.max(0, lp);
    const w  = Math.max(0.3, Math.min(100, rp) - cl);
    return (
      <div
        key={key}
        className="absolute top-1 bottom-1 rounded"
        style={{
          left:            `${cl}%`,
          width:           `${w}%`,
          backgroundColor: colour,
          opacity:         isProjected ? 0.55 : 1,
          backgroundImage: isProjected
            ? "repeating-linear-gradient(90deg,transparent,transparent 4px,rgba(255,255,255,.4) 4px,rgba(255,255,255,.4) 8px)"
            : undefined,
        }}
        onMouseEnter={(ev) => setTooltip({ x: ev.clientX, y: ev.clientY, text: tipText })}
        onMouseLeave={() => setTooltip(null)}
        onMouseMove={(ev)  => setTooltip({ x: ev.clientX, y: ev.clientY, text: tipText })}
      />
    );
  }

  const jumpToNow  = () => setViewStartMs(Date.now() - windowMs * 0.25);
  const fitHistory = () => {
    if (!actualEntries.length) return;
    const starts   = actualEntries.map((e) => new Date(e.start_time).getTime());
    const ends     = actualEntries.map((e) => new Date(e.end_time).getTime());
    const earliest = Math.min(...starts);
    const latest   = Math.max(...ends, Date.now());
    const span     = latest - earliest;
    const pad      = span * 0.1 || 5_000;
    const bestZoom = ZOOM_LEVELS_MS.findIndex((ms) => ms >= span + pad * 2);
    setZoomIdx(bestZoom === -1 ? ZOOM_LEVELS_MS.length - 1 : bestZoom);
    setViewStartMs(earliest - pad);
  };

  const hour     = new Date(now).getHours();
  const isOffice = hour >= 9 && hour < 17;

  return (
    <div className="glass-panel p-4 space-y-2" style={{ userSelect: "none", position: "relative" }}>
      {tooltip && (
        <div
          className="fixed z-50 bg-slate-800 text-white text-[10px] rounded px-2 py-1 shadow-lg pointer-events-none whitespace-nowrap"
          style={{ left: tooltip.x + 12, top: tooltip.y - 32 }}
        >
          {tooltip.text}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-slate-700">Task schedule</h2>
          {bgActive && <span className="text-[10px] text-blue-600 font-mono animate-pulse">● LIVE</span>}
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${isOffice ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
            {isOffice ? "Office hours" : "Out of hours"}
          </span>
          <span className="text-sm font-mono font-bold text-slate-800">
            {new Date(now).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <button onClick={jumpToNow} className="px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-600 hover:bg-blue-50 hover:text-blue-600 transition-colors">
          ↩ Now
        </button>
        {actualEntries.length > 0 && (
          <button onClick={fitHistory} className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors">
            ⊡ Fit history
          </button>
        )}
        <span className="font-mono bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-[10px]">
          {ZOOM_LABELS[zoomIdx]} window
        </span>
        <span className="ml-auto text-[10px] text-slate-400">Scroll to zoom · Drag to pan</span>
      </div>

      <div className="flex gap-0">
        <div style={{ width: LABEL_WIDTH_PX, flexShrink: 0 }}>
          <div style={{ height: 28 }} />
          {rows.map((name) => (
            <div
              key={name}
              className="flex items-center justify-end pr-2 text-[10px] text-slate-500 font-medium"
              style={{ height: 22, marginBottom: 6 }}
              title={name}
            >
              <span className="truncate max-w-[110px]">{name}</span>
            </div>
          ))}
        </div>

        <div
          ref={trackAreaRef}
          className="flex-1 relative overflow-hidden"
          style={{ cursor: isDragging ? "grabbing" : "grab" }}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <div className="relative border-b border-slate-200" style={{ height: 28 }}>
            {ticks.map((tick, i) => (
              <div
                key={i}
                className="absolute top-0 flex flex-col items-center pointer-events-none"
                style={{ left: `${tick.pct}%`, transform: "translateX(-50%)" }}
              >
                <div className="h-2 w-px bg-slate-300 mt-1" />
                <span className="text-[9px] text-slate-400 whitespace-nowrap mt-0.5">{tick.label}</span>
              </div>
            ))}
            {nowPct >= 0 && nowPct <= 100 && (
              <div
                className="absolute top-0 flex flex-col items-center pointer-events-none"
                style={{ left: `${nowPct}%`, transform: "translateX(-50%)" }}
              >
                <div className="h-2 w-0.5 bg-red-400 mt-1" />
                <span className="text-[9px] text-red-400 font-semibold whitespace-nowrap mt-0.5">now</span>
              </div>
            )}
          </div>

          {rows.map((instName) => {
            const cfg      = COLOURS[instName] ?? palette[0];
            const actBars  = actualEntries.filter((e) => e.instrument === instName);
            const projBars = projEntries.filter((e) => e.instrument_name === instName && e.is_projected);
            return (
              <div
                key={instName}
                className="relative rounded"
                style={{ height: 22, marginBottom: 6, backgroundColor: "#f1f5f9" }}
              >
                {ticks.map((tick, i) => (
                  <div key={i} className="absolute top-0 bottom-0 w-px bg-slate-200 pointer-events-none" style={{ left: `${tick.pct}%` }} />
                ))}
                {nowPct >= 0 && nowPct <= 100 && (
                  <div className="absolute top-0 bottom-0 w-0.5 bg-red-400 z-20 pointer-events-none" style={{ left: `${nowPct}%` }} />
                )}
                {projBars.map((e, i) => {
                  const durS = ((new Date(e.end_time).getTime() - new Date(e.start_time).getTime()) / 1000).toFixed(0);
                  return renderBar(`proj-${instName}-${i}`, e.start_time, e.end_time, cfg.proj, `Projected: ${e.label} (${durS}s)`, true);
                })}
                {actBars.map((e, i) => {
                  const durS = ((new Date(e.end_time).getTime() - new Date(e.start_time).getTime()) / 1000).toFixed(1);
                  return renderBar(`actual-${instName}-${i}`, e.start_time, e.end_time, cfg.actual, `${instName}: ${formatTime(e.start_time)} – ${formatTime(e.end_time)} (${durS}s)`, false);
                })}
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-4 text-[10px] text-slate-500 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-2.5 rounded" style={{ backgroundColor: "#06b6d4" }} />
          <span>Actual</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-5 h-2.5 rounded opacity-55" style={{ backgroundColor: "#a5f3fc", backgroundImage: "repeating-linear-gradient(90deg,transparent,transparent 3px,rgba(255,255,255,.5) 3px,rgba(255,255,255,.5) 6px)" }} />
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

      {actualEntries.length > 0 && (
        <div className="border-t border-slate-100 pt-2">
          <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider mb-1.5">Recent activity</div>
          <div className="space-y-0.5 max-h-28 overflow-y-auto">
            {[...actualEntries].reverse().slice(0, 15).map((e, i) => {
              const durS = ((new Date(e.end_time).getTime() - new Date(e.start_time).getTime()) / 1000).toFixed(1);
              const cfg  = COLOURS[e.instrument] ?? palette[0];
              return (
                <div key={i} className="flex items-center justify-between text-[10px]">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: cfg.actual }} />
                    <span className="text-slate-600 font-medium truncate max-w-[120px]">{e.instrument}</span>
                  </div>
                  <span className="font-mono text-slate-400 shrink-0 ml-2">
                    {formatTime(e.start_time)} · {durS}s
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