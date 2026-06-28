import { useState, useRef, useEffect } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Send, Paperclip, CheckCircle2, XCircle,
  Loader2, Zap, User, ChevronDown, ChevronUp,
  Plus, Trash2, Edit3,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Message, ToolCall, WorkflowPlan, WorkflowStep } from "@/types";

export function AgentChat() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const state        = useMaestroStore((s) => s.state);
  const isLoading    = useMaestroStore((s) => s.isLoading);
  const sendMessage  = useMaestroStore((s) => s.sendMessage);
  const confirm      = useMaestroStore((s) => s.confirm);
  const executePlan  = useMaestroStore((s) => s.executePlan);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const [input,     setInput]     = useState("");
  const [uploading, setUploading] = useState(false);
  const fileRef   = useRef<HTMLInputElement>(null);
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

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !sessionId) return;
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      await refreshState();
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="flex flex-col h-full">

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-slate-400 dark:text-slate-500 text-sm italic text-center mt-8">
            Send a message to begin your scientific campaign.
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {/* Working indicator */}
        {state?.background_job_active && state.current_activity && (
          <div className="flex items-start gap-3 animate-fade-in">
            <AgentAvatar />
            <div className="glass-panel px-4 py-3 max-w-[85%]">
              <div className="text-xs text-blue-600 dark:text-blue-400 font-semibold mb-1">
                MAESTRO is working
              </div>
              <div className="text-sm text-slate-600 dark:text-slate-400">
                {state.current_activity}
              </div>
              {state.background_job_plan_length > 0 && (
                <div className="mt-2 w-full h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all duration-500"
                    style={{
                      width: `${Math.min(
                        100,
                        (state.background_job_index / state.background_job_plan_length) * 100
                      )}%`,
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Workflow Plan Editor — shown when agent proposes a plan */}
        {state?.pending_plan && (
          <WorkflowPlanEditor
            plan={state.pending_plan}
            onApprove={executePlan}
            onAbort={() => confirm(false)}
          />
        )}

        {/* Simple confirmation panel — for run_extracted_campaign etc. */}
        {state?.awaiting_confirmation && !state.pending_plan && (
          <ConfirmationPanel
            toolCalls={state.pending_tool_calls}
            onConfirm={() => confirm(true)}
            onAbort={()  => confirm(false)}
          />
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-slate-200 dark:border-slate-700 p-3 space-y-2 shrink-0">
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={handleFileUpload}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className={cn(
              "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors",
              "border-slate-300 dark:border-slate-700",
              "text-slate-500 dark:text-slate-400",
              "hover:border-blue-400 hover:text-blue-600 dark:hover:border-blue-500 dark:hover:text-blue-400",
              uploading && "opacity-50 cursor-not-allowed",
            )}
          >
            {uploading
              ? <Loader2 size={12} className="animate-spin" />
              : <Paperclip size={12} />}
            {uploading ? "Uploading..." : "Attach PDF"}
          </button>

          {state?.active_document_id && (
            <span className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
              <CheckCircle2 size={10} /> Paper loaded
            </span>
          )}
        </div>

        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your scientific objective or ask MAESTRO..."
            rows={2}
            className={cn(
              "flex-1 rounded-lg px-3 py-2 text-sm resize-none",
              "bg-white dark:bg-slate-900",
              "border border-slate-300 dark:border-slate-700",
              "text-slate-800 dark:text-slate-200",
              "placeholder:text-slate-400 dark:placeholder:text-slate-600",
              "focus:outline-none focus:border-blue-400 dark:focus:border-blue-500",
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

// ── Avatars ───────────────────────────────────────────────────────────────────

function AgentAvatar() {
  return (
    <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center shrink-0 shadow-lg shadow-blue-500/20">
      <Zap size={14} className="text-white" />
    </div>
  );
}

function UserAvatar() {
  return (
    <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 flex items-center justify-center shrink-0">
      <User size={14} className="text-slate-600 dark:text-slate-300" />
    </div>
  );
}

// ── Message Bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={cn(
      "flex items-start gap-3 animate-slide-up",
      isUser && "flex-row-reverse",
    )}>
      {isUser ? <UserAvatar /> : <AgentAvatar />}

      <div className={cn(
        "max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed",
        isUser
          ? "bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 text-slate-800 dark:text-slate-200"
          : "glass-panel text-slate-800 dark:text-slate-200",
      )}>
        {message.content ? (
          <ReactMarkdown
            components={{
              img: ({ src, alt }) => (
                <span className="block my-3">
                  <img
                    src={src}
                    alt={alt ?? "Figure"}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 max-w-full h-auto"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                  {alt && alt !== "Figure" && (
                    <span className="block text-xs text-slate-500 mt-1 italic">{alt}</span>
                  )}
                </span>
              ),
              p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              code:   ({ children }) => (
                <code className="bg-slate-100 dark:bg-slate-900 px-1.5 py-0.5 rounded text-xs font-mono text-blue-600 dark:text-blue-400">
                  {children}
                </code>
              ),
              pre:    ({ children }) => (
                <pre className="bg-slate-100 dark:bg-slate-900 rounded-lg p-3 overflow-x-auto text-xs font-mono mt-2">
                  {children}
                </pre>
              ),
              strong: ({ children }) => (
                <strong className="text-blue-600 dark:text-blue-400 font-semibold">{children}</strong>
              ),
              ul: ({ children }) => (
                <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>
              ),
              li: ({ children }) => (
                <li className="text-slate-700 dark:text-slate-300">{children}</li>
              ),
              table: ({ children }) => (
                <table className="w-full text-xs border-collapse mt-2 mb-2">{children}</table>
              ),
              th: ({ children }) => (
                <th className="border border-slate-200 dark:border-slate-700 px-2 py-1 text-left text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-slate-200 dark:border-slate-700 px-2 py-1 text-slate-600 dark:text-slate-400">
                  {children}
                </td>
              ),
            }}
          >
            {message.content}
          </ReactMarkdown>
        ) : (
          <span className="text-slate-400 italic text-xs">
            {message.tool_calls?.map((tc) => `[calling ${tc.function.name}]`).join(", ")}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Workflow Plan Editor ──────────────────────────────────────────────────────

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
    JSON.parse(JSON.stringify(plan))  // deep clone
  );
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(
    new Set(plan.steps.map((s) => s.step_id))
  );

  const toggleStep = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  };

  const updateStep = (stepId: string, field: string, value: unknown) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.map((s) =>
        s.step_id === stepId ? { ...s, [field]: value } : s
      ),
    }));
  };

  const updateFreeParam = (
    stepId: string,
    paramName: string,
    field: "min" | "max",
    value: number,
  ) => {
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

  const updateConditionParam = (
    stepId: string,
    paramName: string,
    value: number,
  ) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => {
        if (s.step_id !== stepId) return s;
        return {
          ...s,
          params: { ...(s.params ?? {}), [paramName]: value },
        };
      }),
    }));
  };

  const removeStep = (stepId: string) => {
    setEditedPlan((prev) => ({
      ...prev,
      steps: prev.steps.filter((s) => s.step_id !== stepId),
    }));
  };

  const stepKindIcon: Record<string, string> = {
    prepare_sample:    "🧪",
    test_sample:       "⚡",
    optimise_condition:"📈",
    list_samples:      "📋",
    query_database:    "💾",
    plotter:           "📊",
    narration:         "💬",
  };

  const stepKindLabel: Record<string, string> = {
    prepare_sample:    "Prepare Sample",
    test_sample:       "Test Sample",
    optimise_condition:"BO Optimisation",
    list_samples:      "List Samples",
    query_database:    "Query Database",
    plotter:           "Generate Plot",
    narration:         "Note",
  };

  return (
    <div className="glass-panel border border-blue-200 dark:border-blue-500/30 p-4 space-y-4 animate-slide-up">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-semibold text-blue-700 dark:text-blue-400 flex items-center gap-2">
            🔬 Proposed Workflow
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            {editedPlan.summary}
          </div>
        </div>
        <div className="text-[10px] text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded">
          {editedPlan.steps.length} step{editedPlan.steps.length !== 1 ? "s" : ""}
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-2">
        {editedPlan.steps.map((step, idx) => (
          <div
            key={step.step_id}
            className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden"
          >
            {/* Step header */}
            <div
              className="flex items-center gap-2 px-3 py-2 bg-slate-50 dark:bg-slate-800/50 cursor-pointer select-none"
              onClick={() => toggleStep(step.step_id)}
            >
              <span className="text-slate-400 dark:text-slate-500 text-xs font-mono w-5 shrink-0">
                {idx + 1}
              </span>
              <span className="text-base">{stepKindIcon[step.kind] ?? "⚙️"}</span>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">
                  {step.label}
                </div>
                <div className="text-[10px] text-slate-400">
                  {stepKindLabel[step.kind] ?? step.kind}
                  {step.instrument && ` · ${step.instrument}`}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={(e) => { e.stopPropagation(); removeStep(step.step_id); }}
                  className="p-1 text-slate-400 hover:text-red-500 transition-colors"
                  title="Remove step"
                >
                  <Trash2 size={12} />
                </button>
                {expandedSteps.has(step.step_id)
                  ? <ChevronUp size={14} className="text-slate-400" />
                  : <ChevronDown size={14} className="text-slate-400" />}
              </div>
            </div>

            {/* Step details — editable */}
            {expandedSteps.has(step.step_id) && (
              <div className="px-3 py-3 space-y-3 bg-white dark:bg-slate-900/50">

                {/* prepare_sample fields */}
                {step.kind === "prepare_sample" && step.params && (
                  <div className="space-y-2">
                    <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Preparation Parameters
                    </div>
                    {Object.entries(step.params).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">{k}</label>
                        <input
                          type="number"
                          value={v}
                          onChange={(e) =>
                            updateConditionParam(step.step_id, k, parseFloat(e.target.value))
                          }
                          className={inputCls}
                          step="0.1"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* test_sample fields */}
                {step.kind === "test_sample" && (
                  <div className="space-y-2">
                    <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                      Test Conditions
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-slate-500 w-32 shrink-0">Sample ref</label>
                      <input
                        type="text"
                        value={step.sample_ref ?? ""}
                        onChange={(e) => updateStep(step.step_id, "sample_ref", e.target.value)}
                        className={inputCls}
                        placeholder="e.g. S-1-001 or {{sample_id}}"
                      />
                    </div>
                    {step.conditions && Object.entries(step.conditions).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">{k}</label>
                        <input
                          type="number"
                          value={v}
                          onChange={(e) =>
                            updateStep(step.step_id, "conditions", {
                              ...(step.conditions ?? {}),
                              [k]: parseFloat(e.target.value),
                            })
                          }
                          className={inputCls}
                          step="1"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* optimise_condition fields */}
                {step.kind === "optimise_condition" && (
                  <div className="space-y-3">
                    <div className="space-y-2">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                        Condition
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">
                          {step.condition_label ?? "condition"}
                        </label>
                        <input
                          type="number"
                          value={step.condition_value ?? 0}
                          onChange={(e) =>
                            updateStep(step.step_id, "condition_value", parseFloat(e.target.value))
                          }
                          className={inputCls}
                          step="1"
                        />
                        <span className="text-xs text-slate-400">{step.condition_unit}</span>
                      </div>
                    </div>

                    {step.free_params && step.free_params.length > 0 && (
                      <div className="space-y-2">
                        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                          Free Parameters (BO search space)
                        </div>
                        {step.free_params.map((p) => (
                          <div key={p.name} className="flex items-center gap-2">
                            <label className="text-xs text-slate-500 w-32 shrink-0">{p.name}</label>
                            <input
                              type="number"
                              value={p.min}
                              onChange={(e) =>
                                updateFreeParam(step.step_id, p.name, "min", parseFloat(e.target.value))
                              }
                              className={cn(inputCls, "w-20")}
                              step="0.1"
                            />
                            <span className="text-xs text-slate-400">to</span>
                            <input
                              type="number"
                              value={p.max}
                              onChange={(e) =>
                                updateFreeParam(step.step_id, p.name, "max", parseFloat(e.target.value))
                              }
                              className={cn(inputCls, "w-20")}
                              step="0.1"
                            />
                            <span className="text-xs text-slate-400">{p.unit}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="space-y-2">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                        BO Settings
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">Iterations</label>
                        <input
                          type="number"
                          value={step.n_calls ?? 20}
                          onChange={(e) =>
                            updateStep(step.step_id, "n_calls", parseInt(e.target.value))
                          }
                          className={cn(inputCls, "w-24")}
                          min="1" max="200" step="1"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500 w-32 shrink-0">Init points</label>
                        <input
                          type="number"
                          value={step.n_initial_points ?? 6}
                          onChange={(e) =>
                            updateStep(step.step_id, "n_initial_points", parseInt(e.target.value))
                          }
                          className={cn(inputCls, "w-24")}
                          min="1" max="50" step="1"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Objective metric (shared) */}
                {(step.kind === "optimise_condition" || step.kind === "test_sample") && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-slate-500 w-32 shrink-0">Objective</label>
                    <span className="text-xs font-mono text-blue-600 dark:text-blue-400">
                      {step.objective_metric ?? step.measures ?? "—"}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Modify hint */}
      <div className="text-xs text-slate-400 dark:text-slate-500 flex items-center gap-1.5">
        <Edit3 size={10} />
        Edit fields above or type in the chat to modify this plan before approving.
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onApprove(editedPlan)}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-500 transition-colors"
        >
          <CheckCircle2 size={14} /> Approve &amp; Run
        </button>
        <button
          onClick={onAbort}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-500/20 border border-red-200 dark:border-red-500/40 text-red-600 dark:text-red-400 text-sm font-medium hover:bg-red-100 dark:hover:bg-red-500/30 transition-colors"
        >
          <XCircle size={14} /> Abort
        </button>
      </div>
    </div>
  );
}

// Shared input class
const inputCls = cn(
  "flex-1 rounded-md px-2 py-1 text-xs",
  "bg-white dark:bg-slate-800",
  "border border-slate-300 dark:border-slate-600",
  "text-slate-800 dark:text-slate-200",
  "focus:outline-none focus:border-blue-400 dark:focus:border-blue-500",
  "transition-colors",
);

// ── Simple Confirmation Panel ─────────────────────────────────────────────────

function ConfirmationPanel({
  toolCalls,
  onConfirm,
  onAbort,
}: {
  toolCalls: ToolCall[];
  onConfirm: () => void;
  onAbort:   () => void;
}) {
  const toolLabels: Record<string, string> = {
    run_extracted_campaign: "Execute paper-grounded experimental campaign",
    plotter:                "Generate multi-panel optimisation summary figure",
    query_database:         "Query experimental database",
  };

  return (
    <div className="glass-panel border border-amber-200 dark:border-amber-500/30 p-4 space-y-3 animate-slide-up">
      <div className="text-sm font-semibold text-amber-700 dark:text-amber-400 flex items-center gap-2">
        ⚠️ Workflow Approval Required
      </div>
      <div className="space-y-1.5">
        {toolCalls.map((tc, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
            <span className="w-4 h-4 rounded bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center text-[10px] font-bold shrink-0">
              {i + 1}
            </span>
            <code className="text-blue-600 dark:text-blue-400">{tc.function.name}</code>
            <span>—</span>
            <span>{toolLabels[tc.function.name] ?? "Execute tool"}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2 pt-1">
        <button
          onClick={onConfirm}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-500 transition-colors"
        >
          <CheckCircle2 size={14} /> Approve &amp; Run
        </button>
        <button
          onClick={onAbort}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-500/20 border border-red-200 dark:border-red-500/40 text-red-600 dark:text-red-400 text-sm font-medium hover:bg-red-100 dark:hover:bg-red-500/30 transition-colors"
        >
          <XCircle size={14} /> Abort
        </button>
      </div>
    </div>
  );
}