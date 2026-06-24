import { useState, useRef } from "react";
import { useMaestroStore } from "@/store/maestroStore";
import { api } from "@/lib/api";
import { Upload, FileText, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Reproducibility() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const state        = useMaestroStore((s) => s.state);
  const refreshState = useMaestroStore((s) => s.refreshState);

  const [uploading,  setUploading]  = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [caseName,   setCaseName]   = useState("Case Study 2: Two-parameter full cells");
  const [dragOver,   setDragOver]   = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!sessionId) return;
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      await refreshState();
    } finally {
      setUploading(false);
    }
  };

  const handleExtract = async () => {
    if (!sessionId || !state?.active_document_id) return;
    setExtracting(true);
    try {
      await api.extractCaseStudy(sessionId, state.active_document_id, caseName);
      await refreshState();
    } finally {
      setExtracting(false);
    }
  };

  const campaign = state?.extracted_campaign;

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">
      <div>
        <h1 className="text-lg font-bold text-slate-100">Scientific Reproducibility</h1>
        <p className="text-xs text-slate-500">Upload a paper and MAESTRO will extract an executable experimental campaign.</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Upload */}
        <div className="space-y-4">
          <div
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f?.type === "application/pdf") handleFile(f); }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onClick={() => fileRef.current?.click()}
            className={cn(
              "glass-panel p-8 flex flex-col items-center gap-3 cursor-pointer transition-colors",
              dragOver ? "border-blue-500 bg-blue-500/5" : "hover:border-blue-500/50"
            )}
          >
            <input ref={fileRef} type="file" accept=".pdf" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
            {uploading
              ? <Loader2 size={32} className="text-blue-400 animate-spin" />
              : state?.active_document_id
              ? <CheckCircle2 size={32} className="text-green-400" />
              : <Upload size={32} className="text-slate-600" />}
            <div className="text-sm font-semibold text-slate-200">
              {uploading ? "Uploading..." : state?.active_document_id ? "Paper loaded ✓" : "Drop PDF here"}
            </div>
            <div className="text-xs text-slate-500 text-center">
              {state?.active_document_id ? "Click to replace" : "or click to browse"}
            </div>
          </div>

          {state?.active_document_id && !campaign && (
            <div className="glass-panel p-4 space-y-3">
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Extract Case Study</div>
              <input
                value={caseName}
                onChange={(e) => setCaseName(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={handleExtract}
                disabled={extracting}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
              >
                {extracting ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
                {extracting ? "Extracting..." : "Extract Campaign"}
              </button>
            </div>
          )}
        </div>

        {/* Campaign display */}
        <div>
          {campaign ? (
            <div className="space-y-4">
              <div className="glass-panel p-4 space-y-3 border-green-500/30 border">
                <div className="flex items-center gap-2 text-green-400 text-xs font-semibold uppercase tracking-wider">
                  <CheckCircle2 size={12} /> Campaign Extracted
                </div>
                <div className="text-base font-bold text-slate-100">{campaign.title}</div>
                <div className="text-xs text-slate-400">{campaign.target_case_study}</div>
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">Objective</div>
                  <div className="text-blue-400 font-mono">{campaign.objective_metric}</div>
                </div>
                <div className="space-y-1 text-xs">
                  <div className="text-slate-500 font-semibold">Parameters</div>
                  {campaign.parameter_space.map((p) => (
                    <div key={p.name} className="flex justify-between">
                      <span className="text-slate-400">{p.name}</span>
                      <span className="font-mono text-slate-200">{p.min}–{p.max} {p.unit}</span>
                    </div>
                  ))}
                </div>
                <div className="text-xs">
                  <div className="text-slate-500 font-semibold mb-1">Feasibility</div>
                  <div className={campaign.capability_match?.lab_can_execute_core_campaign ? "text-green-400" : "text-amber-400"}>
                    {campaign.capability_match?.lab_can_execute_core_campaign ? "✅ Full capability match" : "⚠️ Partial match"}
                  </div>
                </div>
              </div>
              {campaign.assumptions.length > 0 && (
                <div className="glass-panel p-4 space-y-2">
                  <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Assumptions</div>
                  {campaign.assumptions.map((a, i) => (
                    <div key={i} className="text-xs text-slate-500 flex gap-2">
                      <span className="text-amber-400 shrink-0">•</span>{a}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="glass-panel p-10 text-center space-y-2">
              <div className="text-4xl">🔬</div>
              <div className="text-sm font-semibold text-slate-200">No campaign yet</div>
              <div className="text-xs text-slate-500">Upload a paper and extract a case study.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}