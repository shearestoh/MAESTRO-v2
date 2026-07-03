import { useMemo } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { cn } from "@/lib/utils";
import type { WorkflowStep, StepStatus } from "@/types";

const KIND_ICON: Record<string, string> = {
  prepare_sample:    "🧪",
  test_sample:       "⚡",
  optimise_condition:"📈",
  list_samples:      "📋",
  query_database:    "💾",
  generate_plot:     "📊",
  plotter:           "📊",
  analyse_data:      "🔬",
  narration:         "💬",
};

const KIND_LABEL: Record<string, string> = {
  prepare_sample:    "Prepare",
  test_sample:       "Test",
  optimise_condition:"BO Campaign",
  list_samples:      "List Samples",
  query_database:    "Query DB",
  generate_plot:     "Plot",
  plotter:           "Plot",
  analyse_data:      "Analyse",
  narration:         "Note",
};

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

interface ConditionGroup {
  label:     string;
  condition: string;
  steps:     WorkflowStep[];
  status:    StepStatus;
  completed: number;
  total:     number;
  projected_start_min?: number;
  projected_end_min?:   number;
}

function groupSteps(
  plan:     WorkflowStep[],
  statuses: Record<string, StepStatus>,
): { groups: ConditionGroup[]; singles: WorkflowStep[] } {
  const boSteps    = plan.filter((s) => s.kind === "optimise_condition");
  const otherSteps = plan.filter((s) => s.kind !== "optimise_condition");

  const condMap = new Map<string, WorkflowStep[]>();
  for (const step of boSteps) {
    const key = `${step.condition_label}=${step.condition_value}`;
    if (!condMap.has(key)) condMap.set(key, []);
    condMap.get(key)!.push(step);
  }

  const groups: ConditionGroup[] = [];
  for (const [key, steps] of condMap.entries()) {
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

    const completed = stepStatuses.filter((s) => s === "completed").length;

    // Use projected timing from first step in group
    const firstStep = steps[0];

    groups.push({
      label:     firstStep?.label ?? key,
      condition: key,
      steps,
      status,
      completed,
      total: steps.length,
      projected_start_min: firstStep?.projected_start_min,
      projected_end_min:   firstStep?.projected_end_min,
    });
  }

  return { groups, singles: otherSteps };
}

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

  const statuses: Record<string, StepStatus> = state?.step_statuses ?? {};

  const { groups, singles } = useMemo(
    () => groupSteps(rawPlan, statuses),
    [rawPlan, statuses],
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

      {/* Single steps */}
      {singles.map((step) => (
        <SingleStepNode
          key={step.step_id ?? step.kind}
          step={step}
          status={statuses[step.step_id ?? ""] ?? "pending"}
        />
      ))}

      {/* BO condition groups */}
      {groups.map((group) => (
        <ConditionGroupNode
          key={group.condition}
          group={group}
        />
      ))}
    </div>
  );
}

function SingleStepNode({
  step,
  status,
}: {
  step:   WorkflowStep;
  status: StepStatus;
}) {
  const hasProjectedTime =
    step.projected_start_min !== undefined &&
    step.projected_end_min   !== undefined;

  const duration = hasProjectedTime
    ? Math.round((step.projected_end_min! - step.projected_start_min!) * 10) / 10
    : null;

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
        {step.kind === "prepare_sample" && step.params && (
          <div className="text-[10px] opacity-70 truncate">
            {Object.entries(step.params).map(([k, v]) => `${k}=${v}`).join(", ")}
          </div>
        )}
        {step.kind === "test_sample" && (
          <div className="text-[10px] opacity-70 truncate">
            {step.sample_ref} @{" "}
            {Object.entries(step.conditions ?? {}).map(([k, v]) => `${k}=${v}`).join(", ")}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {duration !== null && duration > 0 && (
          <span className="text-[10px] text-slate-400">{duration}min</span>
        )}
        <span className="font-mono text-[11px]">{STATUS_ICON[status]}</span>
      </div>
    </div>
  );
}

function ConditionGroupNode({ group }: { group: ConditionGroup }) {
  const pct = group.total > 0
    ? Math.round((group.completed / group.total) * 100)
    : 0;

  const duration = group.projected_start_min !== undefined &&
                   group.projected_end_min   !== undefined
    ? Math.round(group.projected_end_min - group.projected_start_min)
    : null;

  return (
    <div className={cn(
      "rounded-lg border text-xs overflow-hidden",
      STATUS_STYLES[group.status],
    )}>
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="text-base shrink-0">📈</span>
        <div className="flex-1 min-w-0">
          <div className="font-medium truncate">
            BO @ {group.condition}
          </div>
          <div className="text-[10px] opacity-70">
            {group.completed}/{group.total} iterations
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {duration !== null && duration > 0 && (
            <span className="text-[10px] text-slate-400">~{duration}min</span>
          )}
          <span className="font-mono text-[11px]">
            {STATUS_ICON[group.status]}
          </span>
        </div>
      </div>

      {group.total > 0 && (
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