import { useMaestroStore } from "@/store/maestroStore";
import { cn }              from "@/lib/utils";
import { CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { ResultEntry } from "@/types";

export function Campaign() {
  const state   = useMaestroStore((s) => s.state);
  const [showSpec, setShowSpec] = useState(false);

  const campaign = state?.extracted_campaign;
  const results  = state?.results_store ?? [];

  const getConditionLabel = (r: ResultEntry): string => {
    const label = r.condition_label || "condition";
    const value = r.condition_value  ?? r.power_W ?? 0;
    return `${label} = ${value}`;
  };

  const getBestObjective = (r: ResultEntry): number | null =>
    r.best_objective ?? r.best_energy ?? null;

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">

      {/* Header */}
      <div>
        <h1 className="text-lg font-bold text-slate-100">Campaign</h1>
        <p className="text-xs text-slate-500">
          Understand campaign formulation and track experimental results.
        </p>
      </div>

      {/* ── No campaign state ── */}
      {!campaign && (
        <div className="glass-panel p-10 text-center space-y-3 flex-1 flex flex-col items-center justify-center">
          <div className="text-5xl">🔬</div>
          <div className="text-sm font-semibold text-slate-200">
            No campaign active
          </div>
          <div className="text-xs text-slate-500 max-w-xs">
            Upload a paper in the chat and ask MAESTRO to check feasibility.
            Campaign details will appear here automatically.
          </div>
        </div>
      )}

      {/* ── Campaign spec ── */}
      {campaign && (
        <div className="grid grid-cols-2 gap-4">

          {/* Left: Campaign spec */}
          <div className="space-y-4">
            <div className="glass-panel p-4 space-y-3 border-green-500/30 border">
              <div className="flex items-center gap-2 text-green-400 text-xs font-semibold uppercase tracking-wider">
                <CheckCircle2 size={11} /> Campaign Extracted
              </div>
              <div className="text-base font-bold text-slate-100">
                {campaign.title}
              </div>
              <div className="text-xs text-slate-400">
                {campaign.target_case_study}
              </div>

              {/* Objective */}
              <div className="space-y-1 text-xs">
                <div className="text-slate-500 font-semibold">Objective</div>
                <div className="text-blue-400 font-mono">
                  {campaign.objective_metric}
                </div>
              </div>

              {/* Free parameters */}
              {campaign.parameter_space.length > 0 && (
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">
                    Free Parameters
                  </div>
                  {campaign.parameter_space.map((p) => (
                    <div key={p.name} className="flex justify-between">
                      <span className="text-slate-400">{p.name}</span>
                      <span className="font-mono text-slate-200">
                        {p.min}–{p.max} {p.unit}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Operating conditions */}
              {campaign.operating_conditions.length > 0 && (
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">
                    Operating Conditions
                  </div>
                  {campaign.operating_conditions.map((oc) => (
                    <div key={oc.name} className="flex justify-between">
                      <span className="text-slate-400">{oc.name}</span>
                      <span className="font-mono text-slate-200">
                        {oc.values.join(", ")} {oc.unit}
                        <span className="text-slate-500 ml-1">
                          ({oc.values.length} runs)
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Feasibility */}
              <div className="text-xs">
                <div className="text-slate-500 font-semibold mb-1">
                  Feasibility
                </div>
                <div className={
                  campaign.capability_match?.feasible
                    ? "text-green-400"
                    : "text-amber-400"
                }>
                  {campaign.capability_match?.feasible
                    ? "✅ Full capability match"
                    : "⚠️ Partial match — check assumptions"}
                </div>
              </div>

              {/* Collapsible full spec */}
              <button
                onClick={() => setShowSpec(!showSpec)}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                {showSpec
                  ? <ChevronDown size={12} />
                  : <ChevronRight size={12} />}
                {showSpec ? "Hide" : "Show"} full spec
              </button>
              {showSpec && (
                <pre className="text-[10px] text-slate-500 bg-slate-900 rounded p-2 overflow-auto max-h-48">
                  {JSON.stringify(campaign, null, 2)}
                </pre>
              )}
            </div>

            {/* Assumptions */}
            {campaign.assumptions.length > 0 && (
              <div className="glass-panel p-4 space-y-2">
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Assumptions
                </div>
                {campaign.assumptions.map((a, i) => (
                  <div key={i} className="text-xs text-slate-500 flex gap-2">
                    <span className="text-amber-400 shrink-0">•</span>
                    {a}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: Results */}
          <div className="space-y-4">
            {results.length === 0 ? (
              <div className="glass-panel p-8 text-center space-y-2">
                <div className="text-3xl">📊</div>
                <div className="text-sm font-semibold text-slate-200">
                  No results yet
                </div>
                <div className="text-xs text-slate-500">
                  Ask MAESTRO to run the campaign in the chat.
                </div>
              </div>
            ) : (
              <>
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Experimental Results
                  {state?.active_condition_key && (
                    <span className="ml-2 text-slate-600 normal-case font-normal">
                      — varying {state.active_condition_key}
                    </span>
                  )}
                </div>
                <div className="space-y-3">
                  {results.map((r, idx) => {
                    const condLabel   = getConditionLabel(r);
                    const bestObj     = getBestObjective(r);
                    const objMetric   = campaign.objective_metric ?? "objective";
                    const nEvals      = r.X.length;
                    const progressPct = Math.min(100, (nEvals / 20) * 100);

                    return (
                      <div key={idx} className="glass-panel p-3 space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="text-sm font-bold text-slate-100 truncate">
                            {condLabel}
                          </span>
                          <span className={cn(
                            "text-xs px-2 py-0.5 rounded-full shrink-0",
                            nEvals > 0
                              ? "bg-green-500/20 text-green-400"
                              : "bg-slate-700 text-slate-500",
                          )}>
                            {nEvals} evals
                          </span>
                        </div>

                        {bestObj !== null && (
                          <div className="text-xs text-slate-400">
                            Best {objMetric}:{" "}
                            <span className="text-green-400 font-mono">
                              {bestObj.toFixed(4)}
                            </span>
                          </div>
                        )}

                        {/* Best params */}
                        {r.best_params &&
                          Object.keys(r.best_params).length > 0 && (
                          <div className="text-[10px] text-slate-600 space-y-0.5">
                            {Object.entries(r.best_params).map(([k, v]) => (
                              <div key={k} className="flex justify-between">
                                <span>{k}</span>
                                <span className="font-mono text-slate-500">
                                  {typeof v === "number"
                                    ? v.toFixed(3)
                                    : String(v)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        <div className="w-full h-1 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 transition-all"
                            style={{ width: `${progressPct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}