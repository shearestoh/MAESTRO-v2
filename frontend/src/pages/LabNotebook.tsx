import { useState }         from "react";
import { useMaestroStore }  from "@/store/maestroStore";
import { cn }               from "@/lib/utils";
import {
  CheckCircle2, ChevronDown, ChevronRight,
  AlertTriangle,
} from "lucide-react";
import type { CampaignSpec, ResultEntry, Sample, OutstandingTask } from "@/types";

type Tab = "campaign" | "results" | "samples";

export function LabNotebook() {
  const state      = useMaestroStore((s) => s.state);
  const [tab, setTab] = useState<Tab>("campaign");

const campaign = state?.extracted_campaign ?? null;
  const results        = state?.results_store ?? [];
  const samples        = state?.sample_registry ?? [];
  const outstanding    = state?.outstanding_tasks ?? [];

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "campaign", label: "Campaign" },
    { id: "results",  label: "Results",  count: results.length  },
    { id: "samples",  label: "Samples",  count: samples.length  },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0">
        <h1 className="text-lg font-bold text-slate-800 dark:text-slate-100">
          Lab Notebook
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Understand campaign formulation and track experimental results.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-700 shrink-0 px-6">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
              tab === t.id
                ? "border-blue-500 text-blue-600 dark:text-blue-400"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300",
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded-full font-mono",
                tab === t.id
                  ? "bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-500",
              )}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-6">

        {/* ── Campaign tab ── */}
        {tab === "campaign" && (
          <CampaignTab campaign={campaign} outstanding={outstanding} />
        )}

        {/* ── Results tab ── */}
        {tab === "results" && (
          <ResultsTab
            results={results}
            outstanding={outstanding}
            objectiveMetric={campaign?.objective_metric}
            conditionKey={state?.active_condition_key}
          />
        )}

        {/* ── Samples tab ── */}
        {tab === "samples" && (
          <SamplesTab samples={samples} />
        )}
      </div>
    </div>
  );
}

// ── Campaign Tab ──────────────────────────────────────────────────────────────

function CampaignTab({
  campaign,
  outstanding,
}: {
  campaign:    CampaignSpec | null;
  outstanding: OutstandingTask[];
}) {

  const [showSpec, setShowSpec] = useState(false);

  if (!campaign) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-3">
        <div className="text-5xl">🔬</div>
        <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          No campaign active
        </div>
        <div className="text-xs text-slate-500 max-w-xs text-center">
          Upload a paper in the chat and ask MAESTRO to check feasibility.
          Campaign details will appear here automatically.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-4">
      {/* Campaign spec */}
      <div className="glass-panel p-5 space-y-4 border-green-200 dark:border-green-500/30 border">
        <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-xs font-semibold uppercase tracking-wider">
          <CheckCircle2 size={11} /> Campaign Extracted
        </div>
        <div>
          <div className="text-base font-bold text-slate-800 dark:text-slate-100">
            {campaign.title}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {campaign.target_case_study}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-xs">
          <div>
            <div className="text-slate-500 font-semibold mb-1">Objective</div>
            <div className="text-blue-600 dark:text-blue-400 font-mono">
              {campaign.objective_metric}
            </div>
          </div>
          <div>
            <div className="text-slate-500 font-semibold mb-1">Feasibility</div>
            <div className={
              campaign.capability_match?.feasible
                ? "text-green-600 dark:text-green-400"
                : "text-amber-600 dark:text-amber-400"
            }>
              {campaign.capability_match?.feasible
                ? "✅ Full capability match"
                : "⚠️ Partial match"}
            </div>
          </div>
        </div>

        {campaign.parameter_space.length > 0 && (
          <div className="text-xs space-y-1">
            <div className="text-slate-500 font-semibold">Free Parameters</div>
            {campaign.parameter_space.map((p) => (
              <div key={p.name} className="flex justify-between py-0.5 border-b border-slate-100 dark:border-slate-800">
                <span className="text-slate-600 dark:text-slate-400">{p.name}</span>
                <span className="font-mono text-slate-700 dark:text-slate-200">
                  {p.min}–{p.max} {p.unit}
                </span>
              </div>
            ))}
          </div>
        )}

        {campaign.operating_conditions.length > 0 && (
          <div className="text-xs space-y-1">
            <div className="text-slate-500 font-semibold">Operating Conditions</div>
            {campaign.operating_conditions.map((oc) => (
              <div key={oc.name} className="flex justify-between py-0.5 border-b border-slate-100 dark:border-slate-800">
                <span className="text-slate-600 dark:text-slate-400">{oc.name}</span>
                <span className="font-mono text-slate-700 dark:text-slate-200">
                  {oc.values.join(", ")} {oc.unit}
                  <span className="text-slate-400 ml-1">({oc.values.length} runs)</span>
                </span>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={() => setShowSpec(!showSpec)}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          {showSpec ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {showSpec ? "Hide" : "Show"} full spec
        </button>
        {showSpec && (
          <pre className="text-[10px] text-slate-500 bg-slate-50 dark:bg-slate-900 rounded p-2 overflow-auto max-h-48">
            {JSON.stringify(campaign, null, 2)}
          </pre>
        )}
      </div>

      {/* Assumptions */}
      {campaign.assumptions.length > 0 && (
        <div className="glass-panel p-4 space-y-2">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Assumptions
          </div>
          {campaign.assumptions.map((a, i) => (
            <div key={i} className="text-xs text-slate-600 dark:text-slate-400 flex gap-2">
              <span className="text-amber-500 shrink-0">•</span>
              {a}
            </div>
          ))}
        </div>
      )}

      {/* Outstanding tasks */}
      {outstanding.length > 0 && (
        <div className="glass-panel p-4 space-y-2 border-amber-200 dark:border-amber-500/30 border">
          <div className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
            <AlertTriangle size={11} /> Incomplete Runs
          </div>
          {outstanding.map((t, i) => (
            <div key={i} className="text-xs text-slate-600 dark:text-slate-400 flex justify-between">
              <span>{t.condition_label}={t.condition_value}</span>
              <span className="text-amber-600 dark:text-amber-400">
                {t.completed_calls ?? 0} done, {t.remaining_n_calls} remaining
              </span>
            </div>
          ))}
          <div className="text-[10px] text-slate-400 mt-1">
            Say "continue tomorrow" in the chat to resume these runs.
          </div>
        </div>
      )}
    </div>
  );
}

// ── Results Tab ───────────────────────────────────────────────────────────────

function ResultsTab({
  results,
  outstanding,
  objectiveMetric,
  conditionKey,
}: {
  results:          ResultEntry[];
  outstanding:      OutstandingTask[];
  objectiveMetric?: string;
  conditionKey?:    string;
}) {
  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-3">
        <div className="text-4xl">📊</div>
        <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          No results yet
        </div>
        <div className="text-xs text-slate-500">
          Ask MAESTRO to run the campaign in the chat.
        </div>
      </div>
    );
  }

  const objMetric = objectiveMetric ?? "objective";

  return (
    <div className="space-y-4">
      {conditionKey && (
        <div className="text-xs text-slate-500">
          Varying: <span className="font-mono text-blue-600 dark:text-blue-400">{conditionKey}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {results.map((r, idx) => {
          const label     = r.condition_label || "condition";
          const value     = r.condition_value ?? r.power_W ?? 0;
          const bestObj   = r.best_objective ?? r.best_energy ?? null;
          const nEvals    = r.X.length;
          const pct       = Math.min(100, (nEvals / 20) * 100);
          const isIncomplete = outstanding.some(
            (t) => Math.abs((t.condition_value ?? t.power_W ?? 0) - value) < 1e-9
          );

          return (
            <div
              key={idx}
              className={cn(
                "glass-panel p-4 space-y-3",
                isIncomplete && "border-amber-200 dark:border-amber-500/30 border",
              )}
            >
              <div className="flex justify-between items-center">
                <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
                  {label} = {value}
                </span>
                <div className="flex items-center gap-1.5">
                  {isIncomplete && (
                    <span className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 px-1.5 py-0.5 rounded">
                      incomplete
                    </span>
                  )}
                  <span className={cn(
                    "text-xs px-2 py-0.5 rounded-full",
                    nEvals > 0
                      ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                      : "bg-slate-100 dark:bg-slate-700 text-slate-500",
                  )}>
                    {nEvals} evals
                  </span>
                </div>
              </div>

              {bestObj !== null && (
                <div className="text-xs text-slate-500">
                  Best {objMetric}:{" "}
                  <span className="text-green-600 dark:text-green-400 font-mono font-bold">
                    {bestObj.toFixed(4)}
                  </span>
                </div>
              )}

              {r.best_params && Object.keys(r.best_params).length > 0 && (
                <div className="text-[10px] text-slate-500 space-y-0.5">
                  {Object.entries(r.best_params).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span>{k}</span>
                      <span className="font-mono">{typeof v === "number" ? v.toFixed(3) : String(v)}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="space-y-1">
                <div className="flex justify-between text-[10px] text-slate-400">
                  <span>Progress</span>
                  <span>{nEvals}/20</span>
                </div>
                <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full transition-all rounded-full",
                      isIncomplete ? "bg-amber-400" : "bg-blue-500",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Samples Tab ───────────────────────────────────────────────────────────────

function SamplesTab({ samples }: { samples: Sample[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (samples.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-3">
        <div className="text-4xl">🧪</div>
        <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          No samples in inventory
        </div>
        <div className="text-xs text-slate-500 max-w-xs text-center">
          Ask MAESTRO to prepare a sample, e.g. "make a sample with 92% AM and 50% porosity".
        </div>
      </div>
    );
  }

  const statusColour: Record<string, string> = {
    prepared: "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400",
    tested:   "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400",
    failed:   "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400",
    stored:   "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400",
  };

  const statusIcon: Record<string, string> = {
    prepared: "🧪",
    tested:   "✅",
    failed:   "❌",
    stored:   "📦",
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500">
        {samples.length} sample{samples.length !== 1 ? "s" : ""} in lab inventory
      </div>

      {samples.map((s) => (
        <div key={s.sample_id} className="glass-panel overflow-hidden">
          {/* Sample header */}
          <div
            className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
            onClick={() => toggle(s.sample_id)}
          >
            <span className="text-lg">{statusIcon[s.status] ?? "🧪"}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-slate-800 dark:text-slate-100 font-mono">
                  {s.sample_id}
                </span>
                <span className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                  statusColour[s.status] ?? statusColour.stored,
                )}>
                  {s.status}
                </span>
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {Object.entries(s.params).map(([k, v]) => `${k}=${v}`).join(", ")}
                {" · "}Day {s.prepared_day} {s.prepared_at}
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

          {/* Sample details */}
          {expanded.has(s.sample_id) && (
            <div className="px-4 pb-4 space-y-3 border-t border-slate-100 dark:border-slate-800">

              {/* Preparation params */}
              <div className="pt-3">
                <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  Preparation Parameters
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs">
                  {Object.entries(s.params).map(([k, v]) => (
                    <div key={k} className="flex justify-between py-0.5">
                      <span className="text-slate-500">{k}</span>
                      <span className="font-mono text-slate-700 dark:text-slate-200">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Failure reason */}
              {s.failure_reason && (
                <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 rounded p-2">
                  ❌ {s.failure_reason}
                </div>
              )}

              {/* Test results */}
              {s.results.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Test Results
                  </div>
                  <div className="space-y-2">
                    {s.results.map((r) => (
                      <div
                        key={r.result_id}
                        className="text-xs bg-slate-50 dark:bg-slate-800 rounded p-2 space-y-1"
                      >
                        <div className="flex justify-between text-slate-500">
                          <span>Day {r.tested_day} {r.tested_at}</span>
                          <span className="text-slate-400">{r.tested_by}</span>
                        </div>
                        <div className="flex gap-4">
                          <div>
                            <span className="text-slate-400">Conditions: </span>
                            {Object.entries(r.conditions).map(([k, v]) => (
                              <span key={k} className="font-mono text-slate-600 dark:text-slate-300">
                                {k}={v}{" "}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div>
                          {Object.entries(r.outputs).map(([k, v]) => (
                            <div key={k} className="flex justify-between">
                              <span className="text-slate-500">{k}</span>
                              <span className="font-mono font-bold text-green-600 dark:text-green-400">
                                {v.toFixed(4)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Notes */}
              {s.notes && (
                <div className="text-xs text-slate-500 italic">{s.notes}</div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}