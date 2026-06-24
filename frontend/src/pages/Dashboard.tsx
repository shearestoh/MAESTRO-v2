import { AgentChat }     from "@/components/agent/AgentChat";
import { LabCanvas }     from "@/components/digital-twin/LabCanvas";
import { LiveEventFeed } from "@/components/shared/LiveEventFeed";
import { VirtualClock }  from "@/components/shared/VirtualClock";
import { MetricCard }    from "@/components/shared/MetricCard";
import { useMaestroStore } from "@/store/maestroStore";
import { Activity, Zap, FlaskConical, AlertTriangle } from "lucide-react";

export function Dashboard() {
  const state = useMaestroStore((s) => s.state);

  const totalEvals   = state?.results_store.reduce((s, r) => s + r.X.length, 0) ?? 0;
  const totalFails   = state?.results_store.reduce((s, r) => s + r.failed_samples, 0) ?? 0;
  const bestEnergy   = state?.results_store.reduce((b, r) => Math.max(b, r.best_energy ?? 0), 0) ?? 0;
  const activePowers = state?.results_store.filter((r) => r.X.length > 0).length ?? 0;

  return (
    <div className="flex flex-col h-full gap-4 p-4 overflow-hidden">

      {/* Metric row */}
      <div className="grid grid-cols-4 gap-3 shrink-0">
        <MetricCard label="Evaluations"   value={totalEvals}                        icon={Activity}      accent="blue"  />
        <MetricCard label="Best Energy"   value={`${bestEnergy.toFixed(1)} Wh/kg`}  icon={Zap}           accent="green" />
        <MetricCard label="Active Powers" value={activePowers}                       icon={FlaskConical}  accent="amber" />
        <MetricCard label="Failed Samples"value={totalFails}                         icon={AlertTriangle} accent="red"   />
      </div>

      {/* Main 3-column layout */}
      <div className="flex-1 grid grid-cols-[1fr_1fr_300px] gap-4 min-h-0">

        {/* Chat */}
        <div className="glass-panel flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 shrink-0">
            <h2 className="text-sm font-semibold text-slate-200">Agent Conversation</h2>
            <p className="text-xs text-slate-500">Chat with MAESTRO to design and run experiments</p>
          </div>
          <div className="flex-1 overflow-hidden">
            <AgentChat />
          </div>
        </div>

        {/* Digital Twin + Events */}
        <div className="flex flex-col gap-4 min-h-0">
          <div className="glass-panel flex flex-col flex-1 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700 shrink-0">
              <h2 className="text-sm font-semibold text-slate-200">Digital Twin Lab</h2>
              <p className="text-xs text-slate-500">Live equipment status</p>
            </div>
            <div className="flex-1 p-2 min-h-0">
              <LabCanvas />
            </div>
          </div>
          <div className="h-44 shrink-0">
            <LiveEventFeed />
          </div>
        </div>

        {/* Right panel */}
        <div className="flex flex-col gap-4 overflow-y-auto">
          <VirtualClock />
          <CampaignTimeline />
          <ActivityLog />
        </div>
      </div>
    </div>
  );
}

function CampaignTimeline() {
  const items = useMaestroStore((s) => s.state?.timeline ?? []);

  const styles = {
    done:    "text-green-400",
    active:  "text-blue-400",
    pending: "text-slate-500",
  };
  const icons = { done: "●", active: "◉", pending: "○" };

  return (
    <div className="glass-panel p-4 space-y-2">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
        Campaign Progress
      </div>
      {items.length === 0 && (
        <div className="text-xs text-slate-600 italic">No active campaign.</div>
      )}
      {items.map((item, i) => (
        <div key={i} className={`flex items-start gap-2 text-xs font-medium ${styles[item.status]}`}>
          <span className="shrink-0">{icons[item.status]}</span>
          <span className="leading-tight">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function ActivityLog() {
  const log = useMaestroStore((s) => s.state?.activity_log ?? []);
  return (
    <div className="glass-panel p-4 space-y-2 flex-1">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
        Activity Log
      </div>
      <div className="space-y-1 font-mono text-[11px] text-slate-500 overflow-y-auto max-h-40">
        {log.length === 0 && <div className="italic">No activity yet.</div>}
        {[...log].reverse().map((entry, i) => (
          <div key={i} className="leading-tight">{entry}</div>
        ))}
      </div>
    </div>
  );
}