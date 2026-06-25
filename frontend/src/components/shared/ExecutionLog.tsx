import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

// Only show real lab events — filter WebSocket heartbeats
function isDisplayable(ev: WsEvent): boolean {
  if (ev.event_type === "state_update") return false;
  if (ev.category   === "system")       return false;
  if (!ev.equipment && ev.message === "Working...") return false;
  return true;
}

const categoryColour: Record<string, string> = {
  planning:  "text-blue-400",
  execution: "text-green-400",
  analysis:  "text-amber-400",
  reporting: "text-purple-400",
  knowledge: "text-cyan-400",
};

const equipmentIcon: Record<string, string> = {
  llm:       "🧠",
  optimiser: "📈",
  sampler:   "🧪",
  tester:    "⚡",
  memory:    "💾",
  knowledge: "📚",
  reporting: "📊",
};

export function ExecutionLog() {
  const events  = useMaestroStore((s) => s.liveEvents);
  const log     = useMaestroStore((s) => s.state?.activity_log ?? []);
  const bgActive= useMaestroStore((s) => s.state?.background_job_active ?? false);

  // Real-time WS events take priority; fall back to activity log
  const wsEvents = [...events].filter(isDisplayable).reverse().slice(0, 30);

  return (
    <div className="glass-panel p-3 h-full flex flex-col gap-2 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
          {bgActive
            ? <span className="status-dot active" />
            : <span className="status-dot idle" />}
          Execution Log
        </div>
        {bgActive && (
          <span className="text-[10px] text-blue-400 font-mono animate-pulse">
            LIVE
          </span>
        )}
      </div>

      {/* Events */}
      <div className="flex-1 overflow-y-auto space-y-1 font-mono text-xs">
        {wsEvents.length === 0 && log.length === 0 && (
          <div className="text-slate-600 italic">
            Waiting for agent activity...
          </div>
        )}

        {/* WS events (real-time) */}
        {wsEvents.map((ev, i) => (
          <div
            key={`ws-${i}`}
            className={`flex items-start gap-2 py-0.5 animate-fade-in ${
              categoryColour[ev.category] ?? "text-slate-400"
            }`}
          >
            <span className="shrink-0 w-5 text-center">
              {ev.equipment ? (equipmentIcon[ev.equipment] ?? "⚙️") : "•"}
            </span>
            <span className="leading-tight">{ev.message}</span>
          </div>
        ))}

        {/* Activity log fallback (when no WS events) */}
        {wsEvents.length === 0 &&
          [...log].reverse().slice(0, 15).map((entry, i) => (
            <div key={`log-${i}`} className="text-slate-500 leading-tight">
              {entry}
            </div>
          ))}
      </div>
    </div>
  );
}