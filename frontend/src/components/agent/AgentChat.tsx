import { useState, useRef, useEffect } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { cn } from "@/lib/utils";
import {
  Send, CheckCircle2, XCircle,
  Loader2, User, ChevronDown, ChevronUp,
  Trash2, Edit3,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Message, ToolCall, WorkflowPlan, WorkflowStep } from "@/types";

export function AgentChat() {
  const sessionId   = useMaestroStore((s) => s.sessionId);
  const state       = useMaestroStore((s) => s.state);
  const isLoading   = useMaestroStore((s) => s.isLoading);
  const sendMessage = useMaestroStore((s) => s.sendMessage);
  const confirm     = useMaestroStore((s) => s.confirm);
  const executePlan = useMaestroStore((s) => s.executePlan);

  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const messages: Message[] = (state?.messages ?? []).filter(
    (m) => m.role !== "system" && m.role !== "tool"
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, state?.current_activity, state?.pending_plan]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    await sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-slate-400 text-sm italic text-center mt-8">
            Send a message to begin.
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {state?.background_job_active && state.current_activity && (
          <div className="flex items-start gap-3 animate-fade-in">
            <AgentAvatar />
            <div className="glass-panel px-4 py-3 max-w-[85%]">
              <div className="text-xs text-blue-600 font-semibold mb-1">MAESTRO is working</div>
              <div className="text-sm text-slate-600">{state.current_activity}</div>
              {state.background_job_plan_length > 0 && (
                <div className="mt-2 w-full h-1 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all duration-500"
                    style={{
                      width: `${Math.min(100, (state.background_job_index / state.background_job_plan_length) * 100)}%`,
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {state?.pending_plan && (
          <WorkflowPlanEditor
            plan={state.pending_plan}
            onApprove={executePlan}
            onAbort={() => confirm(false)}
          />
        )}

        {state?.awaiting_confirmation && !state.pending_plan && (
          <ConfirmationPanel
            toolCalls={state.pending_tool_calls}
            onConfirm={() => confirm(true)}
            onAbort={() => confirm(false)}
          />
        )}

        <div ref={bottomRef} />
      </div>

      <div className="border-t border-slate-200 p-3">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your scientific objective or ask MAESTRO..."
            rows={2}
            className={cn(
              "flex-1 rounded-lg px-3 py-2 text-sm resize-none",
              "bg-white border border-slate-300 text-slate-800",
              "placeholder:text-slate-400",
              "focus:outline-none focus:border-blue-400",
              "transition-colors",
            )}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className={cn(
              "px-4 py-2 rounded-lg bg-blue-600 text-white font-medium text-sm",
              "hover:bg-blue-500 transition-colors",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              "flex items-center gap-2 shrink-0",
            )}
          >
            {isLoading
              ? <Loader2 size={16} className="animate-spin" />
              : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}

function AgentAvatar() {
  return (
    <div className="w-8 h-8 shrink-0">
      <svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
        <circle cx="16" cy="16" r="16" fill="#2563eb"/>
        <text x="16" y="22" fontFamily="system-ui, sans-serif" fontSize="18" fontWeight="900" fill="white" textAnchor="middle">M</text>
      </svg>
    </div>
  );
}

function UserAvatar() {
  return (
    <div className="w-8 h-8 rounded-full bg-slate-200 border border-slate-300 flex items-center justify-center shrink-0">
      <User size={14} className="text-slate-600" />
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  if (!isUser && !message.content?.trim()) {
    return null;
  }

  return (
    <div className={cn(
      "flex items-start gap-3 animate-slide-up",
      isUser && "flex-row-reverse",
    )}>
      {isUser ? <UserAvatar /> : <AgentAvatar />}

      <div className={cn(
        "max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed",
        isUser
          ? "bg-blue-50 border border-blue-200 text-slate-800"
          : "glass-panel text-slate-800",
      )}>
        <ReactMarkdown
          components={{
            img: ({ src, alt }) => (
              <span className="block my-3">
                <img
                  src={src}
                  alt={alt ?? "Figure"}
                  className="rounded-lg border border-slate-200 max-w-full h-auto"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                {alt && alt !== "Figure" && (
                  <span className="block text-xs text-slate-500 mt-1 italic">{alt}</span>
                )}
              </span>
            ),
            p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
            code:   ({ children }) => (
              <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs font-mono text-blue-600">
                {children}
              </code>
            ),
            pre:    ({ children }) => (
              <pre className="bg-slate-100 rounded-lg p-3 overflow-x-auto text-xs font-mono mt-2">
                {children}
              </pre>
            ),
            strong: ({ children }) => (
              <strong className="text-blue-600 font-semibold">{children}</strong>
            ),
            ul: ({ children }) => <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>,
            li: ({ children }) => <li className="text-slate-700">{children}</li>,
            table: ({ children }) => <table className="w-full text-xs border-collapse mt-2 mb-2">{children}</table>,
            th: ({ children }) => (
              <th className="border border-slate-200 px-2 py-1 text-left text-slate-700 bg-slate-100">{children}</th>
            ),
            td: ({ children }) => (
              <td className="border border-slate-200 px-2 py-1 text-slate-600">{children}</td>
            ),
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function WorkflowPlanEditor({
  plan,
  onApprove,
  onAbort,
}: {
  plan:      WorkflowPlan;
  onApprove: (plan: WorkflowPlan) => void;
  onAbort:   () => void;
}) {
  const [editedPlan, setEditedPlan] = useState<WorkflowPlan>(
    JSON.parse(JSON.stringify(plan))
  );
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(
    new Set(plan.steps.map((s) => s.step_id))
  );

  const toggleStep = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId); else next.add(stepId);
      return next;
    });
  };

  const updateStep = (stepId: string, field: string, value: unknown) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => s.step_id === stepId ? { ...s, [field]: value } : s),
    }));
  };

  const updateFreeParam = (stepId: string, paramName: string, field: "min" | "max", value: number) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => {
        if (s.step_id !== stepId) return s;
        return {
          ...s,
          free_params: (s.free_params ?? []).map((p) =>
            p.name === paramName ? { ...p, [field]: value } : p
          ),
        };
      }),
    }));
  };

  const updateConditionParam = (stepId: string, paramName: string, value: number) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => {
        if (s.step_id !== stepId) return s;
        return { ...s, params: { ...(s.params ?? {}), [paramName]: value } };
      }),
    }));
  };

  const removeStep = (stepId: string) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.filter((s) => s.step_id !== stepId),
    }));
  };

  function getStepKindIcon(step: WorkflowStep): string {
    if (step.kind === "optimise_condition") {
      const n = (step.optimiser_name ?? "").toLowerCase();
      if (n.includes("random"))   return "🎲";
      if (n.includes("optuna"))   return "🔀";
      if (n.includes("deap"))     return "🧬";
      if (n.includes("honegumi") || n.includes("ax")) return "🧬";
      return "📈"; // default GP-BO
    }
    const icons: Record<string, string> = {
      synthesise:    "🧪",
      characterise:  "⚡",
      list_samples:  "📋",
      query_database:"💾",
      generate_plot: "📊",
      analyse_data:  "📉",
      narration:     "💬",
    };
    return icons[step.kind] ?? "⚙️";
  }

  function getStepKindLabel(step: WorkflowStep): string {
    if (step.kind === "optimise_condition") {
      const n = (step.optimiser_name ?? "").toLowerCase();
      if (n.includes("random"))   return "Random Search";
      if (n.includes("optuna"))   return "Optuna TPE";
      if (n.includes("honegumi") || n.includes("ax")) return "Ax/Honegumi";
      if (n.includes("deap"))     return "Evolutionary (DEAP)";
      if (n.includes("gp") || n.includes("gp_bo")) return "GP-BO";
      if (n)                      return n;
      return "Optimisation";
    }
    const labels: Record<string, string> = {
      synthesise:   "Synthesise",
      characterise: "Characterise",
      list_samples: "List Samples",
      query_database: "Query Database",
      generate_plot:  "Generate Plot",
      analyse_data:   "Analyse Data",
      narration:      "Note",
    };
    return labels[step.kind] ?? step.kind;
  }

  const inputCls = cn(
    "flex-1 rounded-md px-2 py-1 text-xs",
    "bg-white border border-slate-300 text-slate-800",
    "focus:outline-none focus:border-blue-400 transition-colors",
  );

  const hasInvalidBoSteps = editedPlan.steps.some(
    (s) =>
      s.kind === "optimise_condition" &&
      (
        !s.condition_label ||
        s.condition_label === "condition" ||
        s.condition_value === undefined ||
        s.condition_value === null ||
        (s.free_params ?? []).length === 0
      )
  );

  return (
    <div className="glass-panel border border-blue-200 p-4 space-y-4 animate-slide-up">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-semibold text-blue-700 flex items-center gap-2">
            🔬 Proposed workflow
          </div>
          <div className="text-xs text-slate-500 mt-0.5">{editedPlan.summary}</div>
        </div>
        <div className="text-[10px] text-slate-400 bg-slate-100 px-2 py-1 rounded">
          {editedPlan.steps.length} step{editedPlan.steps.length !== 1 ? "s" : ""}
        </div>
      </div>

      <div className="space-y-2">
        {editedPlan.steps.map((step, idx) => (
          <div key={step.step_id} className="border border-slate-200 rounded-lg overflow-hidden">
            <div
              className="flex items-center gap-2 px-3 py-2 bg-slate-50 cursor-pointer select-none"
              onClick={() => toggleStep(step.step_id)}
            >
              <span className="text-slate-400 text-xs font-mono w-5 shrink-0">{idx + 1}</span>
              <span className="text-base">{getStepKindIcon(step)}</span>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-slate-700 truncate">{step.label}</div>
                <div className="text-[10px] text-slate-400 flex items-center gap-1.5 flex-wrap">
                  <span>{getStepKindLabel(step)}</span>
                  {step.instrument && <span>· {step.instrument}</span>}
                  {step.kind === "optimise_condition" && step.optimiser_name && (
                    <span className="px-1 py-0 rounded bg-blue-100 text-blue-600 font-medium">
                      {step.optimiser_name}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={(e) => { e.stopPropagation(); removeStep(step.step_id); }}
                  className="p-1 text-slate-400 hover:text-red-500 transition-colors"
                >
                  <Trash2 size={12} />
                </button>
                {expandedSteps.has(step.step_id)
                  ? <ChevronUp size={14} className="text-slate-400" />
                  : <ChevronDown size={14} className="text-slate-400" />}
              </div>
            </div>

            {expandedSteps.has(step.step_id) && (
              <div className="px-3 py-3 space-y-3 bg-white">

                {/* Synthesise step */}
                {step.kind === "synthesise" && step.params && (
                  <div className="space-y-2">
                    <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Synthesis parameters
                    </div>
                    {Object.entries(step.params).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">{k}</label>
                        <input
                          type="number"
                          value={v}
                          onChange={(e) => updateConditionParam(step.step_id, k, parseFloat(e.target.value))}
                          className={inputCls}
                          step="0.1"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* Characterise step */}
                {step.kind === "characterise" && (
                  <div className="space-y-2">
                    <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Characterisation conditions
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-slate-500 w-32 shrink-0">Sample ref</label>
                      <input
                        type="text"
                        value={step.sample_ref ?? ""}
                        onChange={(e) => updateStep(step.step_id, "sample_ref", e.target.value)}
                        className={inputCls}
                        placeholder="e.g. S-001 or {{sample_id}}"
                      />
                    </div>
                    {step.conditions && Object.entries(step.conditions).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">{k}</label>
                        <input
                          type="number"
                          value={v}
                          onChange={(e) => updateStep(step.step_id, "conditions", {
                            ...(step.conditions ?? {}), [k]: parseFloat(e.target.value),
                          })}
                          className={inputCls}
                          step="1"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* Optimise condition step */}
                {step.kind === "optimise_condition" && (
                  <div className="space-y-3">
                    <div className="space-y-2">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                        Fixed operating condition
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={step.condition_label ?? ""}
                          onChange={(e) => updateStep(step.step_id, "condition_label", e.target.value)}
                          className={cn(inputCls, "w-28")}
                          placeholder="e.g. power_W"
                        />
                        <span className="text-xs text-slate-400">=</span>
                        <input
                          type="number"
                          value={step.condition_value ?? ""}
                          onChange={(e) => updateStep(step.step_id, "condition_value", parseFloat(e.target.value) || 0)}
                          className={cn(inputCls, "w-24")}
                          placeholder="e.g. 80"
                          step="any"
                        />
                        <input
                          type="text"
                          value={step.condition_unit ?? ""}
                          onChange={(e) => updateStep(step.step_id, "condition_unit", e.target.value)}
                          className={cn(inputCls, "w-16")}
                          placeholder="unit"
                        />
                      </div>
                      {(!step.condition_label || step.condition_label === "condition" || !step.condition_value) && (
                        <p className="text-[10px] text-amber-600">
                          Set the operating condition name and value above (e.g. power_W = 80).
                        </p>
                      )}
                    </div>

                    {step.free_params && step.free_params.length > 0 && (
                      <div className="space-y-2">
                        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                          Free parameters (BO search space)
                        </div>
                        {step.free_params.map((p) => (
                          <div key={p.name} className="flex items-center gap-2">
                            <label className="text-xs text-slate-500 w-32 shrink-0">{p.name}</label>
                            <input
                              type="number"
                              value={p.min}
                              onChange={(e) => updateFreeParam(step.step_id, p.name, "min", parseFloat(e.target.value))}
                              className={cn(inputCls, "w-20")}
                              step="0.1"
                            />
                            <span className="text-xs text-slate-400">to</span>
                            <input
                              type="number"
                              value={p.max}
                              onChange={(e) => updateFreeParam(step.step_id, p.name, "max", parseFloat(e.target.value))}
                              className={cn(inputCls, "w-20")}
                              step="0.1"
                            />
                            <span className="text-xs text-slate-400">{p.unit}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {step.free_params && step.free_params.length === 0 && (
                      <div className="text-[10px] text-amber-600">
                        No free parameters defined. Describe the parameters to optimise in the chat.
                      </div>
                    )}

                    <div className="space-y-2">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                        BO settings
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">Iterations</label>
                        <input
                          type="number"
                          value={step.n_calls ?? 20}
                          onChange={(e) => updateStep(step.step_id, "n_calls", parseInt(e.target.value))}
                          className={cn(inputCls, "w-24")}
                          min="1" max="200" step="1"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">Init points</label>
                        <input
                          type="number"
                          value={step.n_initial_points ?? 6}
                          onChange={(e) => updateStep(step.step_id, "n_initial_points", parseInt(e.target.value))}
                          className={cn(inputCls, "w-24")}
                          min="1" max="50" step="1"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {(step.kind === "optimise_condition" || step.kind === "characterise") && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-slate-500 w-32 shrink-0">Objective</label>
                    <span className="text-xs font-mono text-blue-600">
                      {step.objective_metric ?? step.measures ?? "—"}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="text-xs text-slate-400 flex items-center gap-1.5">
        <Edit3 size={10} />
        Edit fields above or describe changes in the chat.
      </div>

      {hasInvalidBoSteps && (
        <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded p-2">
          ⚠️ Complete the operating condition (name + value) and free parameters for all BO steps before approving.
        </p>
      )}

      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onApprove(editedPlan)}
          disabled={hasInvalidBoSteps}
          title={hasInvalidBoSteps ? "Complete all BO step fields before approving" : undefined}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors",
            hasInvalidBoSteps
              ? "bg-slate-200 text-slate-400 cursor-not-allowed"
              : "bg-green-600 text-white hover:bg-green-500",
          )}
        >
          <CheckCircle2 size={14} /> Approve & Run
        </button>
        <button
          onClick={onAbort}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-50 border border-red-200 text-red-600 text-sm font-medium hover:bg-red-100 transition-colors"
        >
          <XCircle size={14} /> Abort
        </button>
      </div>
    </div>
  );
}

function ConfirmationPanel({
  toolCalls,
  onConfirm,
  onAbort,
}: {
  toolCalls: ToolCall[];
  onConfirm: () => void;
  onAbort:   () => void;
}) {
  return (
    <div className="glass-panel border border-amber-200 p-4 space-y-3 animate-slide-up">
      <div className="text-sm font-semibold text-amber-700 flex items-center gap-2">
        ⚠️ Approval required
      </div>
      <div className="space-y-1.5">
        {toolCalls.map((tc, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
            <span className="w-4 h-4 rounded bg-blue-100 text-blue-600 flex items-center justify-center text-[10px] font-bold shrink-0">
              {i + 1}
            </span>
            <code className="text-blue-600">{tc.function.name}</code>
          </div>
        ))}
      </div>
      <div className="flex gap-2 pt-1">
        <button
          onClick={onConfirm}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-500 transition-colors"
        >
          <CheckCircle2 size={14} /> Approve & Run
        </button>
        <button
          onClick={onAbort}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-50 border border-red-200 text-red-600 text-sm font-medium hover:bg-red-100 transition-colors"
        >
          <XCircle size={14} /> Abort
        </button>
      </div>
    </div>
  );
}