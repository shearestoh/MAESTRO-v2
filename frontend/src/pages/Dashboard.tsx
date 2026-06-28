import { AgentChat }        from "@/components/agent/AgentChat";
import { LabCanvas }        from "@/components/digital-twin/LabCanvas";
import { ExecutionLog }     from "@/components/shared/ExecutionLog";
import { ResourceSchedule } from "@/components/shared/ResourceSchedule";
import { PlotViewer }       from "@/components/shared/PlotViewer";
import { MetricCard }       from "@/components/shared/MetricCard";
import { useMaestroStore }  from "@/store/maestroStore";
import { Activity, Zap, FlaskConical, AlertTriangle } from "lucide-react";

export function Dashboard() {
  const state  = useMaestroStore((s) => s.state);

  const labels = state?.metric_labels ?? {
    experiments: "Experiments",
    best_result: "Best Objective",
    conditions:  "Conditions Run",
    failures:    "Failed Steps",
  };

  const totalEvals = state?.results_store.reduce(
    (s, r) => s + r.X.length, 0
  ) ?? 0;

  const totalFails = state?.results_store.reduce(
    (s, r) => s + (r.failed_samples ?? 0), 0
  ) ?? 0;

  const bestResult = state?.results_store.reduce(
    (b, r) => Math.max(b, r.best_objective ?? r.best_energy ?? 0), 0
  ) ?? 0;

  const activeConditions = state?.results_store.filter(
    (r) => r.X.length > 0
  ).length ?? 0;

  return (
    <div className="flex flex-col h-full gap-3 p-4 overflow-hidden">

      {/* Metric row */}
      <div className="grid grid-cols-4 gap-3 shrink-0">
        <MetricCard
          label={labels.experiments}
          value={totalEvals}
          icon={Activity}
          accent="blue"
        />
        <MetricCard
          label={labels.best_result}
          value={bestResult > 0 ? bestResult.toFixed(4) : "—"}
          icon={Zap}
          accent="green"
        />
        <MetricCard
          label={labels.conditions}
          value={activeConditions}
          icon={FlaskConical}
          accent="amber"
        />
        <MetricCard
          label={labels.failures}
          value={totalFails}
          icon={AlertTriangle}
          accent="red"
        />
      </div>

      {/* Main 3-column layout */}
      <div className="flex-1 grid grid-cols-[1fr_1fr_280px] gap-3 min-h-0">

        {/* Chat — renamed, no sub-description */}
        <div className="glass-panel flex flex-col overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-700 shrink-0">
            <h2 className="text-sm font-semibold text-slate-200">
              Chat with MAESTRO
            </h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <AgentChat />
          </div>
        </div>

        {/* Digital Lab — renamed, no sub-description */}
        <div className="flex flex-col gap-3 min-h-0">
          <div className="glass-panel flex flex-col flex-1 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-slate-700 shrink-0">
              <h2 className="text-sm font-semibold text-slate-200">
                Digital Lab
              </h2>
            </div>
            <div className="flex-1 p-2 min-h-0">
              <LabCanvas />
            </div>
          </div>
          <div className="h-44 shrink-0">
            <ExecutionLog />
          </div>
        </div>

        {/* Right panel */}
        <div className="flex flex-col gap-3 overflow-y-auto min-h-0">
          <ResourceSchedule />
          <PlotViewer />
          <CampaignTimeline />
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
    <div className="glass-panel p-4 space-y-2 flex-1">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
        Campaign Progress
      </div>
      {items.length === 0 && (
        <div className="text-xs text-slate-600 italic">
          No active campaign.
        </div>
      )}
      {items.map((item, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 text-xs font-medium ${styles[item.status]}`}
        >
          <span className="shrink-0">{icons[item.status]}</span>
          <span className="leading-tight">{item.label}</span>
        </div>
      ))}
    </div>
  );
}