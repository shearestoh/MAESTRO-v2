import { useState, useRef, useEffect } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Send, Paperclip, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Message, ToolCall } from "@/types";

export function AgentChat() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const state        = useMaestroStore((s) => s.state);
  const isLoading    = useMaestroStore((s) => s.isLoading);
  const sendMessage  = useMaestroStore((s) => s.sendMessage);
  const confirm      = useMaestroStore((s) => s.confirm);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const [input,     setInput]     = useState("");
  const [uploading, setUploading] = useState(false);
  const fileRef  = useRef<HTMLInputElement>(null);
  const bottomRef= useRef<HTMLDivElement>(null);

  const messages: Message[] = (state?.messages ?? []).filter(
    (m) => m.role !== "system" && m.role !== "tool"
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, state?.current_activity]);

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
          <div className="text-slate-500 text-sm italic text-center mt-8">
            Send a message to begin your scientific campaign.
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {/* Working indicator */}
        {state?.background_job_active && state.current_activity && (
          <div className="flex items-start gap-3 animate-fade-in">
            <div className="w-8 h-8 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center shrink-0">
              <Loader2 size={14} className="text-blue-400 animate-spin" />
            </div>
            <div className="glass-panel px-4 py-3 max-w-[85%]">
              <div className="text-xs text-blue-400 font-semibold mb-1">MAESTRO is working</div>
              <div className="text-sm text-slate-400">{state.current_activity}</div>
              {state.background_job_plan_length > 0 && (
                <div className="mt-2 w-full h-1 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all duration-500"
                    style={{
                      width: `${(state.background_job_index / state.background_job_plan_length) * 100}%`,
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Confirmation panel */}
        {state?.awaiting_confirmation && (
          <ConfirmationPanel
            toolCalls={state.pending_tool_calls}
            onConfirm={() => confirm(true)}
            onAbort={()  => confirm(false)}
          />
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-slate-700 p-3 space-y-2 shrink-0">
        {/* File upload */}
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
              "border-slate-700 text-slate-400 hover:border-blue-500 hover:text-blue-400",
              uploading && "opacity-50 cursor-not-allowed"
            )}
          >
            {uploading
              ? <Loader2 size={12} className="animate-spin" />
              : <Paperclip size={12} />}
            {uploading ? "Uploading..." : "Attach PDF"}
          </button>

          {state?.active_document_id && (
            <span className="text-xs text-green-400 flex items-center gap-1">
              <CheckCircle2 size={10} /> Paper loaded
            </span>
          )}
        </div>

        {/* Text input */}
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your scientific objective, ask MAESTRO to run a campaign..."
            rows={2}
            className={cn(
              "flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2",
              "text-sm text-slate-200 placeholder:text-slate-600",
              "resize-none focus:outline-none focus:border-blue-500 transition-colors"
            )}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className={cn(
              "px-4 py-2 rounded-lg bg-blue-600 text-white font-medium text-sm",
              "hover:bg-blue-500 transition-colors",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              "flex items-center gap-2 shrink-0"
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

// ── Message Bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={cn(
      "flex items-start gap-3 animate-slide-up",
      isUser && "flex-row-reverse"
    )}>
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold",
        isUser
          ? "bg-blue-500/20 border border-blue-500/40 text-blue-400"
          : "bg-green-500/20 border border-green-500/40 text-green-400"
      )}>
        {isUser ? "YOU" : "M"}
      </div>

      <div className={cn(
        "max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed",
        isUser
          ? "bg-blue-500/10 border border-blue-500/20 text-slate-200"
          : "glass-panel text-slate-200"
      )}>
        {message.content ? (
          <ReactMarkdown
            components={{
              p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              code:   ({ children }) => (
                <code className="bg-slate-900 px-1.5 py-0.5 rounded text-xs font-mono text-blue-400">
                  {children}
                </code>
              ),
              pre:    ({ children }) => (
                <pre className="bg-slate-900 rounded-lg p-3 overflow-x-auto text-xs font-mono mt-2">
                  {children}
                </pre>
              ),
              strong: ({ children }) => (
                <strong className="text-blue-400 font-semibold">{children}</strong>
              ),
              ul: ({ children }) => <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>,
              li: ({ children }) => <li className="text-slate-300">{children}</li>,
            }}
          >
            {message.content}
          </ReactMarkdown>
        ) : (
          <span className="text-slate-500 italic text-xs">
            {message.tool_calls?.map((tc) => `[calling ${tc.function.name}]`).join(", ")}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Confirmation Panel ────────────────────────────────────────────────────────

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
    query_database:         "Query experimental memory database",
    optimise_new:           "Run Bayesian optimisation campaign",
  };

  return (
    <div className="glass-panel border border-amber-500/30 p-4 space-y-3 animate-slide-up">
      <div className="text-sm font-semibold text-amber-400 flex items-center gap-2">
        ⚠️ Workflow Approval Required
      </div>
      <div className="space-y-1.5">
        {toolCalls.map((tc, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-slate-400">
            <span className="w-4 h-4 rounded bg-blue-500/20 text-blue-400 flex items-center justify-center text-[10px] font-bold shrink-0">
              {i + 1}
            </span>
            <code className="text-blue-400">{tc.function.name}</code>
            <span>—</span>
            <span>{toolLabels[tc.function.name] ?? "Execute tool"}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2 pt-1">
        <button
          onClick={onConfirm}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-500/20 border border-green-500/40 text-green-400 text-sm font-medium hover:bg-green-500/30 transition-colors"
        >
          <CheckCircle2 size={14} /> Approve & Run
        </button>
        <button
          onClick={onAbort}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 text-sm font-medium hover:bg-red-500/30 transition-colors"
        >
          <XCircle size={14} /> Abort
        </button>
      </div>
    </div>
  );
}