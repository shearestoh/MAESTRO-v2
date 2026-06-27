import { useState, useRef } from "react";
import { useMaestroStore }  from "@/store/maestroStore";
import { api }              from "@/lib/api";
import { cn }               from "@/lib/utils";
import {
  Upload, FileText, CheckCircle2,
  Loader2, ChevronDown, ChevronRight,
} from "lucide-react";
import type { ResultEntry } from "@/types";

export function Campaign() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const state        = useMaestroStore((s) => s.state);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const [uploading,  setUploading]  = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [caseName,   setCaseName]   = useState("Case Study 2");
  const [dragOver,   setDragOver]   = useState(false);
  const [showSpec,   setShowSpec]   = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const campaign = state?.extracted_campaign;
  const results  = state?.results_store ?? [];

  // ── Helpers ────────────────────────────────────────────────────────────────

  const handleFile = async (file: File) => {
    if (!sessionId) return;
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      await refreshState();
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleExtract = async () => {
    if (!sessionId || !state?.active_document_id) return;
    setExtracting(true);
    try {
      await api.extractCaseStudy(
        sessionId, state.active_document_id, caseName
      );
      await refreshState();
    } finally {
      setExtracting(false);
    }
  };

  // ── Condition display helper ───────────────────────────────────────────────
  // Uses general fields with power_W fallback for backward compat

  const getConditionLabel = (r: ResultEntry): string => {
    const label = r.condition_label || "power_W";
    const value = r.condition_value  ?? r.power_W ?? 0;
    return `${label} = ${value}`;
  };

  const getBestObjective = (r: ResultEntry): number | null =>
    r.best_objective ?? r.best_energy ?? null;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">

      {/* Header */}
      <div>
        <h1 className="text-lg font-bold text-slate-100">Campaign</h1>
        <p className="text-xs text-slate-500">
          Upload a paper, extract a campaign, and track experimental results.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">

        {/* ── Left: Paper upload + extraction ── */}
        <div className="space-y-4">

          {/* PDF Upload */}
          <div
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files[0];
              if (f?.type === "application/pdf") handleFile(f);
            }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onClick={() => fileRef.current?.click()}
            className={cn(
              "glass-panel p-6 flex flex-col items-center gap-3",
              "cursor-pointer transition-colors",
              dragOver
                ? "border-blue-500 bg-blue-500/5"
                : "hover:border-blue-500/50",
            )}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
            {uploading ? (
              <Loader2 size={28} className="text-blue-400 animate-spin" />
            ) : state?.active_document_id ? (
              <CheckCircle2 size={28} className="text-green-400" />
            ) : (
              <Upload size={28} className="text-slate-600" />
            )}
            <div className="text-sm font-semibold text-slate-200 text-center">
              {uploading
                ? "Uploading..."
                : state?.active_document_id
                ? "Paper loaded ✓"
                : "Drop PDF here or click to browse"}
            </div>
            {state?.active_document_id && (
              <div className="text-xs text-slate-500 text-center">
                Click to replace with a different paper
              </div>
            )}
          </div>

          {/* Case study extraction */}
          {state?.active_document_id && (
            <div className="glass-panel p-4 space-y-3">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Extract Case Study
              </div>
              <input
                value={caseName}
                onChange={(e) => setCaseName(e.target.value)}
                placeholder="e.g. Case Study 2, Figure 3 experiment..."
                className={cn(
                  "w-full bg-slate-900 border border-slate-700 rounded-lg",
                  "px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600",
                  "focus:outline-none focus:border-blue-500",
                )}
              />
              <button
                onClick={handleExtract}
                disabled={extracting || !caseName.trim()}
                className={cn(
                  "w-full flex items-center justify-center gap-2 px-4 py-2",
                  "rounded-lg bg-blue-600 text-white text-sm font-medium",
                  "hover:bg-blue-500 transition-colors disabled:opacity-50",
                )}
              >
                {extracting
                  ? <Loader2 size={14} className="animate-spin" />
                  : <FileText size={14} />}
                {extracting ? "Extracting..." : "Extract & Check Feasibility"}
              </button>
              <p className="text-[10px] text-slate-600">
                Or ask MAESTRO in the chat: "reproduce Case Study 2, is it feasible?"
              </p>
            </div>
          )}
        </div>

        {/* ── Right: Campaign spec ── */}
        <div className="space-y-4">
          {campaign ? (
            <>
              {/* Campaign spec card */}
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
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">
                    Free Parameters (BO search space)
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

                {/* Operating conditions */}
                {campaign.operating_conditions.length > 0 && (
                  <div className="space-y-1 text-xs">
                    <div className="text-slate-500 font-semibold">
                      Operating Conditions (separate runs)
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
            </>
          ) : (
            <div className="glass-panel p-8 text-center space-y-2">
              <div className="text-4xl">📋</div>
              <div className="text-sm font-semibold text-slate-200">
                No campaign extracted yet
              </div>
              <div className="text-xs text-slate-500">
                Upload a paper and extract a case study, or ask MAESTRO in the chat.
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Results section ── */}
      {results.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Experimental Results
            {state?.active_condition_key && (
              <span className="ml-2 text-slate-600 normal-case font-normal">
                — varying {state.active_condition_key}
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-3">
            {results.map((r, idx) => {
              const condLabel   = getConditionLabel(r);
              const bestObj     = getBestObjective(r);
              const objMetric   = campaign?.objective_metric ?? "objective";
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

                  {/* Best params summary */}
                  {r.best_params && Object.keys(r.best_params).length > 0 && (
                    <div className="text-[10px] text-slate-600 space-y-0.5">
                      {Object.entries(r.best_params).map(([k, v]) => (
                        <div key={k} className="flex justify-between">
                          <span>{k}</span>
                          <span className="font-mono text-slate-500">
                            {typeof v === "number" ? v.toFixed(2) : v}
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
        </div>
      )}
    </div>
  );
}