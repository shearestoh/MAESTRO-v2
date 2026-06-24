import { useMaestroStore } from "@/store/maestroStore";
import type { WsEvent } from "@/types";

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

function isDisplayableEvent(ev: WsEvent): boolean {
  // Filter out:
  // 1. WebSocket heartbeat/system events (state_update)
  // 2. Events with no equipment and no meaningful category
  // 3. Generic "Working..." messages with no context
  if (ev.event_type === "state_update") return false;
  if (ev.category === "system") return false;
  if (!ev.equipment && ev.message === "Working...") return false;
  return true;
}

export function LiveEventFeed() {
  const events = useMaestroStore((s) => s.liveEvents);
  const log    = useMaestroStore((s) => s.state?.activity_log ?? []);

  // Only show real lab events — filter out heartbeats
  const displayed = [...events]
    .filter(isDisplayableEvent)
    .reverse()
    .slice(0, 20);

  return (
    <div className="glass-panel p-3 h-full flex flex-col gap-2 overflow-hidden">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2 shrink-0">
        <span className="status-dot active" />
        Live Activity
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 font-mono text-xs">
        {displayed.length === 0 && log.length === 0 && (
          <div className="text-slate-600 italic">
            Waiting for agent activity...
          </div>
        )}

        {displayed.length === 0 && log.length > 0 &&
          [...log].reverse().slice(0, 10).map((entry, i) => (
            <div key={i} className="text-slate-500 leading-tight">
              {entry}
            </div>
          ))}

        {displayed.map((ev, i) => (
          <div
            key={i}
            className={`flex items-start gap-2 py-0.5 animate-fade-in ${
              categoryColour[ev.category] ?? "text-slate-400"
            }`}
          >
            <span className="shrink-0 w-5 text-center">
              {ev.equipment
                ? (equipmentIcon[ev.equipment] ?? "⚙️")
                : "•"}
            </span>
            <span className="leading-tight">{ev.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}