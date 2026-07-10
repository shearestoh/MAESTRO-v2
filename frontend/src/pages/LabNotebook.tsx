import { useState }        from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { cn }              from "@/lib/utils";
import { ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import type { Sample, ResultEntry, OutstandingTask, WorkflowStep } from "@/types";
import { getBestOutput } from "@/lib/utils";

type Tab = "synthesis" | "characterisation" | "computation";

export function LabNotebook() {
  const state = useMaestroStore((s) => s.state);
  const [tab, setTab] = useState<Tab>("synthesis");

  const samples = state?.sample_registry ?? [];
  const results = state?.results_store   ?? [];

  const synthesisSamples = samples.filter(
    (s) => s.status === "prepared" || s.status === "tested" || s.status === "failed"
  );
  const characterisationSamples = samples.filter((s) => s.results.length > 0);

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: "synthesis",        label: "Synthesis",        count: synthesisSamples.length },
    { id: "characterisation", label: "Characterisation", count: characterisationSamples.length },
    { id: "computation",      label: "Computation",      count: results.length },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-50">
      <div className="px-6 py-4 border-b border-slate-200 shrink-0 bg-white">
        <h1 className="text-lg font-bold text-slate-800">Lab Notebook</h1>
        <p className="text-xs text-slate-500">Recorded experimental data from all lab instruments.</p>
      </div>

      <div className="flex border-b border-slate-200 shrink-0 px-6 bg-white">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
              tab === t.id
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-slate-500 hover:text-slate-700",
            )}
          >
            {t.label}
            {t.count > 0 && (
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded-full font-mono",
                tab === t.id ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500",
              )}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {tab === "synthesis"        && <SynthesisTab samples={synthesisSamples} />}
        {tab === "characterisation" && (
          <CharacterisationTab
            samples={characterisationSamples}
            outstanding={state?.outstanding_tasks ?? []}
            objectiveMetric={state?.extracted_campaign?.objective_metric}
            conditionKey={state?.active_condition_key}
          />
        )}
        {tab === "computation" && (
          <ComputationTab
            results={results}
            backgroundPlan={state?.background_job_plan ?? []}
            defaultNCalls={state?.optimiser_config?.n_calls ?? 20}
          />
        )}
      </div>
    </div>
  );
}

function SynthesisTab({ samples }: { samples: Sample[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  if (samples.length === 0) {
    return (
      <EmptyState
        icon="🧪"
        title="No synthesis records"
        description="Synthesised samples will appear here. Ask MAESTRO to synthesise a sample or run a campaign."
      />
    );
  }

  const statusColour: Record<string, string> = {
    prepared: "bg-blue-100 text-blue-700",
    tested:   "bg-green-100 text-green-700",
    failed:   "bg-red-100 text-red-700",
    stored:   "bg-slate-100 text-slate-600",
  };
  const statusIcon: Record<string, string> = {
    prepared: "🧪", tested: "✅", failed: "❌", stored: "📦",
  };

  return (
    <div className="space-y-2 max-w-3xl">
      <div className="text-xs text-slate-500 mb-3">
        {(() => {
          const successful = samples.filter((s) => s.status === "prepared" || s.status === "tested").length;
          const failed     = samples.filter((s) => s.status === "failed").length;
          const parts      = [`${successful} synthesised`];
          if (failed > 0) parts.push(`${failed} failed`);
          return parts.join(", ");
        })()}
      </div>
      {samples.map((s) => (
        <div key={s.sample_id} className="glass-panel overflow-hidden">
          <div
            className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors"
            onClick={() => toggle(s.sample_id)}
          >
            <span className="text-lg">{statusIcon[s.status] ?? "🧪"}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-slate-800 font-mono">{s.sample_id}</span>
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", statusColour[s.status] ?? statusColour.stored)}>
                  {s.status}
                </span>
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {Object.entries(s.params).map(([k, v]) => `${k}=${v}`).join(", ")}
                {" · "}{s.prepared_by}
                {" · "}{s.prepared_at ? new Date(s.prepared_at).toLocaleString() : ""}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {s.results.length > 0 && (
                <span className="text-[10px] text-slate-400">
                  {s.results.length} test{s.results.length !== 1 ? "s" : ""}
                </span>
              )}
              {expanded.has(s.sample_id)
                ? <ChevronDown size={14} className="text-slate-400" />
                : <ChevronRight size={14} className="text-slate-400" />}
            </div>
          </div>

          {expanded.has(s.sample_id) && (
            <div className="px-4 pb-4 space-y-3 border-t border-slate-100">
              <div className="pt-3">
                <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  Synthesis Parameters
                </div>
                <div className="grid grid-cols-3 gap-1 text-xs">
                  {Object.entries(s.params).map(([k, v]) => (
                    <div key={k} className="flex justify-between py-0.5 border-b border-slate-100">
                      <span className="text-slate-500">{k}</span>
                      <span className="font-mono text-slate-700">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
              {s.failure_reason && (
                <div className="text-xs text-red-600 bg-red-50 rounded p-2">❌ {s.failure_reason}</div>
              )}
              {s.notes && <div className="text-xs text-slate-500 italic">{s.notes}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function CharacterisationTab({
  samples, outstanding, objectiveMetric, conditionKey,
}: {
  samples:          Sample[];
  outstanding:      OutstandingTask[];
  objectiveMetric?: string;
  conditionKey?:    string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  if (samples.length === 0) {
    return (
      <EmptyState
        icon="⚡"
        title="No characterisation records"
        description="Characterisation results will appear here. Ask MAESTRO to characterise a sample or run a campaign."
      />
    );
  }

  const objMetric = objectiveMetric ?? "objective";

  return (
    <div className="space-y-2 max-w-3xl">
      <div className="text-xs text-slate-500 mb-3">
        {samples.length} sample{samples.length !== 1 ? "s" : ""} characterised
        {conditionKey && (
          <span className="ml-2">
            · varying <span className="font-mono text-blue-600">{conditionKey}</span>
          </span>
        )}
      </div>

      {outstanding.length > 0 && (
        <div className="glass-panel p-3 border-amber-200 border mb-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 mb-2">
            <AlertTriangle size={11} /> Incomplete Runs
          </div>
          {outstanding.map((t, i) => (
            <div key={i} className="text-xs text-slate-600 flex justify-between">
              <span>{t.condition_label}={t.condition_value}</span>
              <span className="text-amber-600">
                {t.completed_calls ?? 0} done, {t.remaining_n_calls} remaining
              </span>
            </div>
          ))}
        </div>
      )}

      {samples.map((s) => {
        const bestVal = getBestOutput(s, objMetric);
        return (
          <div key={s.sample_id} className="glass-panel overflow-hidden">
            <div
              className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors"
              onClick={() => toggle(s.sample_id)}
            >
              <span className="text-lg">⚡</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-800 font-mono">{s.sample_id}</span>
                  <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">
                    {s.results.length} test{s.results.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {Object.entries(s.params).map(([k, v]) => `${k}=${v}`).join(", ")}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {bestVal !== null && (
                  <span className="text-xs font-mono text-green-600 font-bold">
                    {bestVal.toFixed(3)}
                  </span>
                )}
                {expanded.has(s.sample_id)
                  ? <ChevronDown size={14} className="text-slate-400" />
                  : <ChevronRight size={14} className="text-slate-400" />}
              </div>
            </div>

            {expanded.has(s.sample_id) && (
              <div className="px-4 pb-4 space-y-2 border-t border-slate-100">
                <div className="pt-3 text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  Characterisation Results
                </div>
                {s.results.map((r) => (
                  <div key={r.result_id} className="text-xs bg-slate-50 rounded p-2 space-y-1">
                    <div className="flex justify-between text-slate-500">
                      <span>{r.tested_at ? new Date(r.tested_at).toLocaleString() : ""}</span>
                      <span className="text-slate-400">{r.tested_by}</span>
                    </div>
                    <div className="text-slate-600">
                      <span className="text-slate-400">Conditions: </span>
                      {Object.entries(r.conditions).map(([k, v]) => (
                        <span key={k} className="font-mono">{k}={v} </span>
                      ))}
                    </div>
                    {Object.entries(r.outputs).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span className="text-slate-500">{k}</span>
                        <span className="font-mono font-bold text-green-600">{v.toFixed(4)}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ComputationTab({
  results, backgroundPlan, defaultNCalls,
}: {
  results:        ResultEntry[];
  backgroundPlan: WorkflowStep[];
  defaultNCalls:  number;
}) {
  if (results.length === 0) {
    return (
      <EmptyState
        icon="📈"
        title="No computation records"
        description="Optimisation results will appear here. Run a campaign to see results."
      />
    );
  }

  // Build comparison summary if multiple optimisers present
  const optimisers = [...new Set(results.map((r) => r.optimiser_name || "unknown"))];
  const hasMultiple = optimisers.length > 1;

  return (
    <div className="space-y-3 max-w-3xl">
      <div className="text-xs text-slate-500 mb-3">
        {results.length} optimisation run{results.length !== 1 ? "s" : ""}
        {hasMultiple && (
          <span className="ml-2 text-blue-600">
            · {optimisers.length} optimisers compared
          </span>
        )}
      </div>

      {/* Comparison summary table */}
      {hasMultiple && (
        <div className="glass-panel p-3 border-blue-100 border mb-2">
          <div className="text-xs font-semibold text-slate-600 mb-2">
            Optimiser comparison
          </div>
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-1 pr-4">Condition</th>
                <th className="pb-1 pr-4">Optimiser</th>
                <th className="pb-1 pr-4">Best objective</th>
                <th className="pb-1">Evaluations</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-1 pr-4 font-mono text-slate-700">
                    {r.condition_label} = {r.condition_value}
                  </td>
                  <td className="py-1 pr-4">
                    <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-medium">
                      {r.optimiser_name || "unknown"}
                    </span>
                  </td>
                  <td className="py-1 pr-4 font-mono text-green-600 font-bold">
                    {r.best_objective !== null ? r.best_objective.toFixed(4) : "—"}
                  </td>
                  <td className="py-1 text-slate-500">
                    {r.X.length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Individual run cards */}
      {results.map((r, idx) => {
        // ── Extract fields individually — NEVER concatenate them ──
        const conditionLabel = r.condition_label || "condition";
        const conditionValue = r.condition_value ?? 0;
        const optimiserName  = r.optimiser_name  || "";
        const bestObj        = r.best_objective  ?? null;
        const nEvals       = r.X.length;
        const matchingStep = backgroundPlan.find(
          (s) =>
            s.condition_label === r.condition_label &&
            Math.abs((s.condition_value ?? 0) - r.condition_value) < 1e-9 &&
            (s.optimiser_name ?? "") === r.optimiser_name
        );
        const nCallsTarget = matchingStep?.n_calls ?? defaultNCalls;
        const progressPct  = Math.min(100, (nEvals / nCallsTarget) * 100);

        return (
          <div key={idx} className="glass-panel p-4 space-y-3">

            {/* Header row: condition + optimiser badge + eval count */}
            <div className="flex justify-between items-start gap-2">
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                {/* Condition — standalone, no concatenation */}
                <span className="text-sm font-bold text-slate-800">
                  {conditionLabel} = {conditionValue}
                </span>
                {/* Optimiser — separate badge element */}
                {optimiserName && (
                  <span className="text-[10px] text-blue-600 bg-blue-50 border border-blue-200 px-1.5 py-0.5 rounded font-medium whitespace-nowrap">
                    {optimiserName}
                  </span>
                )}
              </div>
              <span className={cn(
                "text-xs px-2 py-0.5 rounded-full shrink-0",
                nEvals > 0 ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500",
              )}>
                {nEvals} evals
              </span>
            </div>

            {/* Best objective */}
            {bestObj !== null && (
              <div className="text-xs text-slate-500">
                Best objective:{" "}
                <span className="text-green-600 font-mono font-bold">
                  {bestObj.toFixed(4)}
                </span>
              </div>
            )}

            {/* Best parameters */}
            {r.best_params && Object.keys(r.best_params).length > 0 && (
              <div className="text-[10px] text-slate-500 space-y-0.5">
                <div className="font-semibold text-slate-600 mb-1">Best parameters:</div>
                {Object.entries(r.best_params).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span>{k}</span>
                    <span className="font-mono">
                      {typeof v === "number" ? v.toFixed(3) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Progress bar */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>Progress</span>
                <span>{nEvals}/{nCallsTarget}</span>
              </div>
              <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all rounded-full"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({ icon, title, description }: { icon: string; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 space-y-3">
      <div className="text-5xl opacity-30">{icon}</div>
      <div className="text-sm font-semibold text-slate-600">{title}</div>
      <div className="text-xs text-slate-400 max-w-xs text-center">{description}</div>
    </div>
  );
}