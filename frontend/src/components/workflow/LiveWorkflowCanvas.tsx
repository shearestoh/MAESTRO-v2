import { useMemo } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { cn } from "@/lib/utils";
import type { WorkflowStep, StepStatus } from "@/types";

// ── Icon / label maps ─────────────────────────────────────────────────────────

const KIND_ICON: Record<string, string> = {
  synthesise:        "🧪",
  characterise:      "⚡",
  optimise_condition:"🔬",
  list_samples:      "📋",
  query_database:    "💾",
  generate_plot:     "📊",
  analyse_data:      "📉",
  narration:         "💬",
};

const KIND_LABEL: Record<string, string> = {
  synthesise:        "Synthesise",
  characterise:      "Characterise",
  optimise_condition:"Optimisation",
  list_samples:      "List Samples",
  query_database:    "Query DB",
  generate_plot:     "Plot",
  analyse_data:      "Analyse",
  narration:         "Note",
};

// Map optimiser name → short display label + icon
function getOptimiserDisplay(name: string | undefined): { label: string; icon: string } {
  if (!name) return { label: "Optimise", icon: "🔬" };
  const n = name.toLowerCase();
  if (n.includes("gp") || n.includes("gp_bo") || n.includes("bayesian") || n.includes("skopt"))
    return { label: "GP-BO",         icon: "📈" };
  if (n.includes("random"))
    return { label: "Random Search", icon: "🎲" };
  if (n.includes("optuna") || n.includes("tpe"))
    return { label: "Optuna TPE",    icon: "🔀" };
  if (n.includes("honegumi") || n.includes("ax"))
    return { label: "Ax/Honegumi",   icon: "🧬" };
  if (n.includes("deap") || n.includes("evolution"))
    return { label: "Evolutionary",  icon: "🧬" };
  return { label: name, icon: "🔬" };
}

// ── Status styles ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<StepStatus, string> = {
  pending:   "bg-slate-50 border-slate-200 text-slate-500",
  running:   "bg-blue-50 border-blue-300 text-blue-700 animate-pulse",
  completed: "bg-green-50 border-green-300 text-green-700",
  failed:    "bg-red-50 border-red-300 text-red-700",
  skipped:   "bg-amber-50 border-amber-300 text-amber-700",
};

const STATUS_ICON: Record<StepStatus, string> = {
  pending:   "○",
  running:   "◉",
  completed: "●",
  failed:    "✕",
  skipped:   "⊘",
};

// ── Grouping ──────────────────────────────────────────────────────────────────

interface ConditionGroup {
  label:            string;
  condition:        string;
  optimiserName?:   string;
  steps:            WorkflowStep[];
  status:           StepStatus;
  currentIteration: number;
  totalIterations:  number;
}

function groupSteps(
  plan:              WorkflowStep[],
  statuses:          Record<string, StepStatus>,
  boIterationCounts: Record<string, number>,
): { groups: ConditionGroup[]; singles: WorkflowStep[] } {
  const boSteps    = plan.filter((s) => s.kind === "optimise_condition");
  const otherSteps = plan.filter((s) => s.kind !== "optimise_condition");

  // Key includes optimiser so same condition with different optimisers are separate groups
  const condMap = new Map<string, WorkflowStep[]>();
  for (const step of boSteps) {
    const key = `${step.condition_label}=${step.condition_value}|${step.optimiser_name ?? ""}`;
    if (!condMap.has(key)) condMap.set(key, []);
    condMap.get(key)!.push(step);
  }

  const groups: ConditionGroup[] = [];
  for (const [, steps] of condMap.entries()) {
    const stepStatuses = steps.map(
      (s) => statuses[s.step_id ?? ""] ?? "pending"
    );
    const hasRunning  = stepStatuses.some((s) => s === "running");
    const allComplete = stepStatuses.every((s) => s === "completed");
    const hasFailed   = stepStatuses.some((s) => s === "failed");
    const status: StepStatus = hasFailed
      ? "failed"
      : allComplete
      ? "completed"
      : hasRunning
      ? "running"
      : "pending";

    const firstStep        = steps[0];
    const currentIteration = firstStep?.step_id
      ? (boIterationCounts[firstStep.step_id] ?? 0)
      : 0;
    const totalIterations  = firstStep?.n_calls ?? 20;

    groups.push({
      label:            firstStep?.label ?? "",
      condition:        `${firstStep?.condition_label}=${firstStep?.condition_value}`,
      optimiserName:    firstStep?.optimiser_name,
      steps,
      status,
      currentIteration,
      totalIterations,
    });
  }

  return { groups, singles: otherSteps };
}

// ── Main component ────────────────────────────────────────────────────────────

export function LiveWorkflowCanvas() {
  const state    = useMaestroStore((s) => s.state);
  const bgActive = state?.background_job_active ?? false;
  const pending  = state?.pending_plan;

  const rawPlan: WorkflowStep[] = useMemo(() => {
    if (pending) return pending.steps;
    if (state?.background_job_plan) {
      return state.background_job_plan as unknown as WorkflowStep[];
    }
    return [];
  }, [pending, state?.background_job_plan]);

  const statuses:          Record<string, StepStatus> = state?.step_statuses      ?? {};
  const boIterationCounts: Record<string, number>     = state?.bo_iteration_counts ?? {};

  const { groups, singles } = useMemo(
    () => groupSteps(rawPlan, statuses, boIterationCounts),
    [rawPlan, statuses, boIterationCounts],
  );

  const hasContent = groups.length > 0 || singles.length > 0;

  if (!hasContent) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-xs text-slate-400">No workflow running.</div>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-y-auto p-3 space-y-2">

      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
          {pending ? "Proposed Workflow" : "Live Workflow"}
        </div>
        {bgActive && (
          <span className="text-[10px] text-blue-600 font-mono animate-pulse">
            RUNNING
          </span>
        )}
      </div>

      {/* Non-BO steps */}
      {singles.map((step) => (
        <SingleStepNode
          key={step.step_id ?? step.kind}
          step={step}
          status={statuses[step.step_id ?? ""] ?? "pending"}
        />
      ))}

      {/* BO / optimisation groups */}
      {groups.map((group) => (
        <ConditionGroupNode
          key={`${group.condition}|${group.optimiserName ?? ""}`}
          group={group}
        />
      ))}
    </div>
  );
}

// ── Single step node ──────────────────────────────────────────────────────────

function SingleStepNode({
  step,
  status,
}: {
  step:   WorkflowStep;
  status: StepStatus;
}) {
  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs",
      STATUS_STYLES[status],
    )}>
      <span className="text-base shrink-0">
        {KIND_ICON[step.kind] ?? "⚙️"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">
          {step.label || KIND_LABEL[step.kind] || step.kind}
        </div>
        {step.kind === "synthesise" && step.params && Object.keys(step.params).length > 0 && (
          <div className="text-[10px] opacity-70 truncate">
            {Object.entries(step.params).map(([k, v]) => `${k}=${v}`).join(", ")}
          </div>
        )}
        {step.kind === "characterise" && (
          <div className="text-[10px] opacity-70 truncate">
            {step.sample_ref}
            {step.conditions && Object.keys(step.conditions).length > 0 && (
              <> @ {Object.entries(step.conditions).map(([k, v]) => `${k}=${v}`).join(", ")}</>
            )}
          </div>
        )}
        {step.kind === "optimise_condition" && step.condition_label && (
          <div className="text-[10px] opacity-70 truncate">
            {step.condition_label}={step.condition_value} {step.condition_unit ?? ""}
          </div>
        )}
      </div>
      <span className="font-mono text-[11px] shrink-0">{STATUS_ICON[status]}</span>
    </div>
  );
}

// ── Condition group node (optimisation steps) ─────────────────────────────────

function ConditionGroupNode({ group }: { group: ConditionGroup }) {
  const pct = group.totalIterations > 0
    ? Math.round((group.currentIteration / group.totalIterations) * 100)
    : 0;

  const { label: optLabel, icon: optIcon } = getOptimiserDisplay(group.optimiserName);

  return (
    <div className={cn(
      "rounded-lg border text-xs overflow-hidden",
      STATUS_STYLES[group.status],
    )}>
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="text-base shrink-0">{optIcon}</span>
        <div className="flex-1 min-w-0">
          {/* Show the actual step label from the LLM (e.g. "Optimise under 80W") */}
          <div className="font-medium truncate">
            {group.label || `Optimise @ ${group.condition}`}
          </div>
          <div className="text-[10px] opacity-70 flex items-center gap-1.5">
            <span>{group.currentIteration}/{group.totalIterations} iterations</span>
            {/* Optimiser badge */}
            <span className="px-1 py-0 rounded bg-white/50 font-medium">
              {optLabel}
            </span>
          </div>
        </div>
        <span className="font-mono text-[11px] shrink-0">
          {STATUS_ICON[group.status]}
        </span>
      </div>

      {group.totalIterations > 0 && (
        <div className="px-3 pb-2">
          <div className="w-full h-1.5 bg-white/50 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                group.status === "completed" ? "bg-green-500" :
                group.status === "failed"    ? "bg-red-500"   :
                group.status === "running"   ? "bg-blue-500"  :
                "bg-slate-300",
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}