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

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">
      <div>
        <h1 className="text-lg font-bold text-slate-800">Campaign</h1>
        <p className="text-xs text-slate-500">
          Campaign formulation and experimental results.
        </p>
      </div>

      {!campaign && (
        <div className="glass-panel p-10 text-center space-y-3 flex-1 flex flex-col items-center justify-center">
          <div className="text-5xl">🔬</div>
          <div className="text-sm font-semibold text-slate-700">No campaign active</div>
          <div className="text-xs text-slate-500 max-w-xs">
            Upload a paper in the chat and ask MAESTRO to check feasibility,
            or ask MAESTRO to run an optimisation campaign directly.
            Campaign details will appear here automatically.
          </div>
        </div>
      )}

      {campaign && (
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-4">
            <div className="glass-panel p-4 space-y-3 border-green-500/30 border">
              <div className="flex items-center gap-2 text-green-600 text-xs font-semibold uppercase tracking-wider">
                <CheckCircle2 size={11} /> Campaign Extracted
              </div>
              <div className="text-base font-bold text-slate-800">{campaign.title}</div>
              <div className="text-xs text-slate-500">{campaign.target_case_study}</div>

              <div className="space-y-1 text-xs">
                <div className="text-slate-500 font-semibold">Objective</div>
                <div className="text-blue-600 font-mono">{campaign.objective_metric}</div>
              </div>

              {campaign.parameter_space.length > 0 && (
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">Free Parameters</div>
                  {campaign.parameter_space.map((p) => (
                    <div key={p.name} className="flex justify-between">
                      <span className="text-slate-500">{p.name}</span>
                      <span className="font-mono text-slate-700">{p.min}–{p.max} {p.unit}</span>
                    </div>
                  ))}
                </div>
              )}

              {campaign.operating_conditions.length > 0 && (
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">Operating Conditions</div>
                  {campaign.operating_conditions.map((oc) => (
                    <div key={oc.name} className="flex justify-between">
                      <span className="text-slate-500">{oc.name}</span>
                      <span className="font-mono text-slate-700">
                        {oc.values.join(", ")} {oc.unit}
                        <span className="text-slate-400 ml-1">({oc.values.length} runs)</span>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="text-xs">
                <div className="text-slate-500 font-semibold mb-1">Feasibility</div>
                <div className={campaign.capability_match?.feasible ? "text-green-600" : "text-amber-600"}>
                  {campaign.capability_match?.feasible
                    ? "✅ Full capability match"
                    : "⚠️ Partial match — check assumptions"}
                </div>
              </div>

              <button
                onClick={() => setShowSpec(!showSpec)}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 transition-colors"
              >
                {showSpec ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                {showSpec ? "Hide" : "Show"} full spec
              </button>
              {showSpec && (
                <pre className="text-[10px] text-slate-500 bg-slate-50 rounded p-2 overflow-auto max-h-48">
                  {JSON.stringify(campaign, null, 2)}
                </pre>
              )}
            </div>

            {campaign.assumptions.length > 0 && (
              <div className="glass-panel p-4 space-y-2">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Assumptions</div>
                {campaign.assumptions.map((a, i) => (
                  <div key={i} className="text-xs text-slate-500 flex gap-2">
                    <span className="text-amber-500 shrink-0">•</span>{a}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-4">
            {results.length === 0 ? (
              <div className="glass-panel p-8 text-center space-y-2">
                <div className="text-3xl">📊</div>
                <div className="text-sm font-semibold text-slate-700">No results yet</div>
                <div className="text-xs text-slate-500">Ask MAESTRO to run the campaign in the chat.</div>
              </div>
            ) : (
              <>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Experimental Results
                  {state?.active_condition_key && (
                    <span className="ml-2 text-slate-400 normal-case font-normal">
                      — varying {state.active_condition_key}
                    </span>
                  )}
                </div>
                <div className="space-y-3">
                  {results.map((r, idx) => {
                    const condLabel   = r.condition_label || "condition";
                    const condValue   = r.condition_value ?? 0;
                    const bestObj     = r.best_objective ?? null;
                    const objMetric   = campaign.objective_metric ?? "objective";
                    const nEvals = r.X.length;
                    // Use the step's own n_calls if available in the background plan,
                    // otherwise fall back to the session optimiser config default.
                    const matchingStep = (state?.background_job_plan ?? []).find(
                      (s) =>
                        s.condition_label === r.condition_label &&
                        Math.abs((s.condition_value ?? 0) - r.condition_value) < 1e-9 &&
                        (s.optimiser_name ?? "") === r.optimiser_name
                    );
                    const nCallsTarget = matchingStep?.n_calls ?? state?.optimiser_config?.n_calls ?? 20;
                    const progressPct  = Math.min(100, (nEvals / nCallsTarget) * 100);

                    return (
                      <div key={idx} className="glass-panel p-3 space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="text-sm font-bold text-slate-800 truncate">
                            {condLabel} = {condValue}
                          </span>
                          <span className={cn(
                            "text-xs px-2 py-0.5 rounded-full shrink-0",
                            nEvals > 0 ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500",
                          )}>
                            {nEvals} evals
                          </span>
                        </div>

                        {bestObj !== null && (
                          <div className="text-xs text-slate-500">
                            Best {objMetric}:{" "}
                            <span className="text-green-600 font-mono">{bestObj.toFixed(4)}</span>
                          </div>
                        )}

                        {r.best_params && Object.keys(r.best_params).length > 0 && (
                          <div className="text-[10px] text-slate-500 space-y-0.5">
                            {Object.entries(r.best_params).map(([k, v]) => (
                              <div key={k} className="flex justify-between">
                                <span>{k}</span>
                                <span className="font-mono text-slate-400">
                                  {typeof v === "number" ? v.toFixed(3) : String(v)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        <div className="w-full h-1 bg-slate-100 rounded-full overflow-hidden">
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