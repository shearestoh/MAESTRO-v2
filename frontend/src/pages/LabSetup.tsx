import { useState, useEffect, useRef } from "react";
import { useMaestroStore }   from "@/store/maestroStore";
import { api }               from "@/lib/api";
import { cn }                from "@/lib/utils";
import {
  Plus, Trash2, Save, Upload, FileText,
  CheckCircle2, Loader2, FlaskConical, Cpu, ExternalLink,
} from "lucide-react";
import type {
  VirtualInstrument, LabSettings,
  OptimisationLibraryEntry, DocumentLibraryEntry, DocumentType,
} from "@/types";

type Tab = "instruments" | "optimisation" | "library" | "settings";

export function LabSetup() {
  const [tab, setTab] = useState<Tab>("instruments");

  const tabs: { id: Tab; label: string }[] = [
    { id: "instruments",  label: "Instruments"  },
    { id: "optimisation", label: "Optimisation" },
    { id: "library",      label: "Library"      },
    { id: "settings",     label: "Settings"     },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-50">
      <div className="px-6 py-4 border-b border-slate-200 shrink-0 bg-white">
        <h1 className="text-lg font-bold text-slate-800">Lab Setup</h1>
        <p className="text-xs text-slate-500">
          Configure instruments, optimisation libraries, knowledge library, and lab settings.
        </p>
      </div>

      <div className="flex border-b border-slate-200 shrink-0 px-6 bg-white">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
              tab === t.id
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-slate-500 hover:text-slate-700",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-6">
        {tab === "instruments"  && <InstrumentsTab />}
        {tab === "optimisation" && <OptimisationTab />}
        {tab === "library"      && <LibraryTab />}
        {tab === "settings"     && <SettingsTab />}
      </div>
    </div>
  );
}

// ── Instruments Tab ───────────────────────────────────────────────────────────

function InstrumentsTab() {
  const [instruments, setInstruments] = useState<VirtualInstrument[]>([]);
  const [showForm,    setShowForm]    = useState(false);
  const [editTarget,  setEditTarget]  = useState<VirtualInstrument | null>(null);
  const [loading,     setLoading]     = useState(true);

  useEffect(() => {
    api.listTools().then((res) => {
      setInstruments(res.tools);
      setLoading(false);
    });
  }, []);

  const handleDelete = async (toolId: string) => {
    await api.deleteTool(toolId);
    setInstruments((prev) => prev.filter((t) => t.tool_id !== toolId));
  };

  const handleSaved = (instrument: VirtualInstrument) => {
    setInstruments((prev) => {
      const idx = prev.findIndex((t) => t.tool_id === instrument.tool_id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = instrument;
        return next;
      }
      return [...prev, instrument];
    });
    setShowForm(false);
    setEditTarget(null);
  };

  const physical      = instruments.filter((i) => i.category === "physical");
  const computational = instruments.filter(
    (i) => i.category === "computational" && i.sub_category !== "optimiser"
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Loader2 size={20} className="animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <div className="flex justify-end">
        <button
          onClick={() => { setEditTarget(null); setShowForm(true); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors"
        >
          <Plus size={12} /> Add Instrument
        </button>
      </div>

      <InstrumentSection
        title="Physical Instruments"
        icon={<FlaskConical size={14} className="text-slate-500" />}
        instruments={physical}
        onEdit={(inst) => { setEditTarget(inst); setShowForm(true); }}
        onDelete={handleDelete}
        emptyMessage="No physical instruments registered. Add synthesis or characterisation instruments."
      />

      <InstrumentSection
        title="Computational Instruments"
        icon={<Cpu size={14} className="text-slate-500" />}
        instruments={computational}
        onEdit={(inst) => { setEditTarget(inst); setShowForm(true); }}
        onDelete={handleDelete}
        emptyMessage="No computational instruments registered. Add databases, simulation or modelling tools."
      />

      {showForm && (
        <InstrumentForm
          initial={editTarget}
          onSaved={handleSaved}
          onCancel={() => { setShowForm(false); setEditTarget(null); }}
        />
      )}
    </div>
  );
}

function InstrumentSection({
  title, icon, instruments, onEdit, onDelete, emptyMessage,
}: {
  title:        string;
  icon:         React.ReactNode;
  instruments:  VirtualInstrument[];
  onEdit:       (inst: VirtualInstrument) => void;
  onDelete:     (id: string) => void;
  emptyMessage: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
          {instruments.length}
        </span>
      </div>
      {instruments.length === 0 ? (
        <div className="glass-panel p-4 text-center text-slate-400 text-xs">
          {emptyMessage}
        </div>
      ) : (
        <div className="space-y-2">
          {instruments.map((inst) => (
            <InstrumentRow
              key={inst.tool_id}
              instrument={inst}
              onEdit={() => onEdit(inst)}
              onDelete={() => onDelete(inst.tool_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function InstrumentRow({
  instrument, onEdit, onDelete,
}: {
  instrument: VirtualInstrument;
  onEdit:     () => void;
  onDelete:   () => void;
}) {
  const subCatIcon: Record<string, string> = {
    synthesis:      "🧪",
    characterisation:"⚡",
    simulation:     "💻",
    modelling:      "🧮",
    data:           "💾",
  };

  return (
    <div className="glass-panel px-4 py-3 flex items-center gap-3">
      <span className="text-xl">{subCatIcon[instrument.sub_category] ?? "⚙️"}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-800">{instrument.name}</span>
          {instrument.is_default && (
            <span className="text-[9px] text-slate-400 bg-slate-100 px-1 py-0.5 rounded">default</span>
          )}
          <span className="text-[9px] text-slate-400 bg-slate-100 px-1 py-0.5 rounded">
            {instrument.sub_category || instrument.kind}
          </span>
        </div>
        <div className="text-xs text-slate-500 truncate mt-0.5">
          {instrument.parameters.length > 0 && (
            <span>in: {instrument.parameters.map((p) => p.name).join(", ")}</span>
          )}
          {instrument.outputs.length > 0 && (
            <span> · out: {instrument.outputs.map((o) => o.name).join(", ")}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {instrument.time_cost_min > 0 && (
          <span className="text-[10px] text-slate-400">{instrument.time_cost_min}s</span>
        )}
        <button onClick={onEdit} className="text-xs text-slate-400 hover:text-blue-600 transition-colors px-2 py-1">
          Edit
        </button>
        <button onClick={onDelete} className="text-slate-400 hover:text-red-500 transition-colors p-1">
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}

interface ParamDef  { name: string; min: string; max: string; unit: string; description: string; }
interface OutputDef { name: string; unit: string; description: string; }

function InstrumentForm({
  initial, onSaved, onCancel,
}: {
  initial:  VirtualInstrument | null;
  onSaved:  (inst: VirtualInstrument) => void;
  onCancel: () => void;
}) {
  const [name,        setName]        = useState(initial?.name        ?? "");
  const [category,    setCategory]    = useState(initial?.category    ?? "physical");
  const [subCategory, setSubCategory] = useState(initial?.sub_category ?? "synthesis");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [timeCost,    setTimeCost]    = useState(String(initial?.time_cost_min ?? 5));
  const [failRate,    setFailRate]    = useState(
    String(((initial?.failure_modes?.[0]?.probability ?? 0) * 100).toFixed(0))
  );
  const [failDesc, setFailDesc] = useState(initial?.failure_modes?.[0]?.description ?? "");
  const [params,  setParams]  = useState<ParamDef[]>(
    initial?.parameters.map((p) => ({
      name: p.name, min: String(p.min ?? ""), max: String(p.max ?? ""),
      unit: p.unit, description: p.description,
    })) ?? []
  );
  const [outputs, setOutputs] = useState<OutputDef[]>(
    initial?.outputs.map((o) => ({
      name: o.name, unit: o.unit, description: o.description,
    })) ?? []
  );
  const [saving, setSaving] = useState(false);

  const physicalSubCats      = ["synthesis", "characterisation"];
  const computationalSubCats = ["simulation", "modelling", "data"];
  const subCatOptions        = category === "physical" ? physicalSubCats : computationalSubCats;

  const addParam  = () => setParams((p)  => [...p,  { name: "", min: "", max: "", unit: "", description: "" }]);
  const addOutput = () => setOutputs((o) => [...o,  { name: "", unit: "", description: "" }]);

  const updateParam  = (i: number, field: keyof ParamDef,  val: string) =>
    setParams((p)  => p.map((x, j) => j === i ? { ...x, [field]: val } : x));
  const updateOutput = (i: number, field: keyof OutputDef, val: string) =>
    setOutputs((o) => o.map((x, j) => j === i ? { ...x, [field]: val } : x));

  const handleSave = async () => {
    setSaving(true);
    const payload = {
      name,
      kind:         subCategory,
      category,
      sub_category: subCategory,
      description,
      time_cost_min: parseFloat(timeCost) || 0,
      parameters: params.map((p) => ({
        name: p.name, type: "continuous",
        min: parseFloat(p.min) || null,
        max: parseFloat(p.max) || null,
        unit: p.unit, description: p.description, required: true,
      })),
      outputs: outputs.map((o) => ({
        name: o.name, type: "scalar", unit: o.unit, description: o.description,
      })),
      failure_modes: failRate && parseFloat(failRate) > 0 ? [{
        name: "failure",
        description: failDesc || "Instrument failure",
        probability: parseFloat(failRate) / 100,
      }] : [],
      enabled:    true,
      is_default: false,
      metadata:   {},
    };
    try {
      let result;
      if (initial) {
        result = await api.updateTool(initial.tool_id, payload);
      } else {
        result = await api.registerTool(payload);
      }
      onSaved(result.tool);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const inputCls = cn(
    "w-full rounded-md px-2 py-1.5 text-xs",
    "bg-white border border-slate-300 text-slate-800",
    "focus:outline-none focus:border-blue-400",
  );

  return (
    <div className="glass-panel p-5 space-y-4 border-blue-200 border">
      <h3 className="text-sm font-semibold text-slate-700">
        {initial ? "Edit Instrument" : "Add Instrument"}
      </h3>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Name</label>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Potentiostat" />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Category</label>
          <select
            className={inputCls}
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setSubCategory(e.target.value === "physical" ? "synthesis" : "simulation");
            }}
          >
            <option value="physical">Physical</option>
            <option value="computational">Computational</option>
          </select>
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Type</label>
          <select className={inputCls} value={subCategory} onChange={(e) => setSubCategory(e.target.value)}>
            {subCatOptions.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
          Description (read by MAESTRO agent)
        </label>
        <textarea
          className={cn(inputCls, "resize-none")}
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what this instrument does, what parameters it accepts, and what it measures..."
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Input Parameters</label>
          <button onClick={addParam} className="text-[10px] text-blue-600 hover:underline">+ Add</button>
        </div>
        {params.map((p, i) => (
          <div key={i} className="grid grid-cols-5 gap-1.5 mb-1.5">
            <input className={inputCls} placeholder="name"  value={p.name} onChange={(e) => updateParam(i, "name",  e.target.value)} />
            <input className={inputCls} placeholder="min"   value={p.min}  onChange={(e) => updateParam(i, "min",   e.target.value)} type="number" />
            <input className={inputCls} placeholder="max"   value={p.max}  onChange={(e) => updateParam(i, "max",   e.target.value)} type="number" />
            <input className={inputCls} placeholder="unit"  value={p.unit} onChange={(e) => updateParam(i, "unit",  e.target.value)} />
            <button onClick={() => setParams((prev) => prev.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-600 text-xs">✕</button>
          </div>
        ))}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Measurable Outputs</label>
          <button onClick={addOutput} className="text-[10px] text-blue-600 hover:underline">+ Add</button>
        </div>
        {outputs.map((o, i) => (
          <div key={i} className="grid grid-cols-4 gap-1.5 mb-1.5">
            <input className={inputCls} placeholder="name"        value={o.name}        onChange={(e) => updateOutput(i, "name",        e.target.value)} />
            <input className={inputCls} placeholder="unit"        value={o.unit}        onChange={(e) => updateOutput(i, "unit",        e.target.value)} />
            <input className={inputCls} placeholder="description" value={o.description} onChange={(e) => updateOutput(i, "description", e.target.value)} />
            <button onClick={() => setOutputs((prev) => prev.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-600 text-xs">✕</button>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Time cost (s)</label>
          <input className={inputCls} type="number" value={timeCost} onChange={(e) => setTimeCost(e.target.value)} min="0" />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Failure rate (%)</label>
          <input className={inputCls} type="number" value={failRate} onChange={(e) => setFailRate(e.target.value)} min="0" max="100" />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Failure description</label>
          <input className={inputCls} value={failDesc} onChange={(e) => setFailDesc(e.target.value)} placeholder="e.g. Sample defect" />
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {saving ? "Saving..." : "Save Instrument"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded-lg border border-slate-300 text-slate-600 text-xs font-medium hover:bg-slate-50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Optimisation Tab ──────────────────────────────────────────────────────────

function OptimisationTab() {
  const optimisationLibrary     = useMaestroStore((s) => s.optimisationLibrary);
  const loadOptimisationLibrary = useMaestroStore((s) => s.loadOptimisationLibrary);

  const [showAdd,  setShowAdd]  = useState(false);
  const [newEntry, setNewEntry] = useState<Partial<OptimisationLibraryEntry>>({
    name: "", description: "", capabilities: [], install_cmd: "", docs_url: "",
  });

  useEffect(() => {
    if (optimisationLibrary.length === 0) loadOptimisationLibrary();
  }, [optimisationLibrary.length, loadOptimisationLibrary]);

  const handleAddEntry = async () => {
    if (!newEntry.name?.trim()) return;
    try {
      await api.addToOptimisationLibrary(newEntry);
      await loadOptimisationLibrary();
      setShowAdd(false);
      setNewEntry({ name: "", description: "", capabilities: [], install_cmd: "", docs_url: "" });
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveEntry = async (libId: string) => {
    try {
      await api.removeFromOptimisationLibrary(libId);
      await loadOptimisationLibrary();
    } catch (e) {
      console.error(e);
    }
  };

  const inputCls = cn(
    "rounded-md px-2 py-1.5 text-xs",
    "bg-white border border-slate-300 text-slate-800",
    "focus:outline-none focus:border-blue-400",
  );

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-1">Optimisation library</h3>
        <p className="text-xs text-slate-500 mb-4">
          MAESTRO reads these descriptions and selects the most appropriate algorithm
          for each task, including proposing suitable hyperparameters. Add or remove
          libraries to guide the agent's choices.
        </p>
        <div className="space-y-3">
          {optimisationLibrary.map((lib) => (
            <div key={lib.lib_id} className="glass-panel p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{lib.name}</span>
                    {lib.is_default && (
                      <span className="text-[9px] text-slate-400 bg-slate-100 px-1 py-0.5 rounded">built-in</span>
                    )}
                    {!lib.enabled && (
                      <span className="text-[9px] text-amber-600 bg-amber-50 px-1 py-0.5 rounded">disabled</span>
                    )}
                  </div>
                  <p className="text-xs text-slate-600 mt-1">{lib.description}</p>
                  {lib.capabilities.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {lib.capabilities.map((c) => (
                        <span key={c} className="text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
                          {c}
                        </span>
                      ))}
                    </div>
                  )}
                  {lib.install_cmd && (
                    <code className="text-[10px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded mt-1 block">
                      {lib.install_cmd}
                    </code>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {lib.docs_url && (
                    <a
                      href={lib.docs_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-400 hover:text-blue-600 transition-colors"
                    >
                      <ExternalLink size={12} />
                    </a>
                  )}
                  {!lib.is_default && (
                    <button
                      onClick={() => handleRemoveEntry(lib.lib_id)}
                      className="text-slate-400 hover:text-red-500 transition-colors"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={() => setShowAdd(!showAdd)}
          className="mt-3 flex items-center gap-1.5 text-xs text-blue-600 hover:underline"
        >
          <Plus size={12} /> Add custom library
        </button>

        {showAdd && (
          <div className="glass-panel p-4 mt-3 space-y-3 border-blue-200 border">
            <h4 className="text-sm font-semibold text-slate-700">Add optimisation library</h4>
            <input
              className={cn(inputCls, "w-full")}
              placeholder="Library name (e.g. BoTorch)"
              value={newEntry.name ?? ""}
              onChange={(e) => setNewEntry((p) => ({ ...p, name: e.target.value }))}
            />
            <textarea
              className={cn(inputCls, "w-full resize-none")}
              rows={2}
              placeholder="Description — what tasks is it good for? The agent will read this."
              value={newEntry.description ?? ""}
              onChange={(e) => setNewEntry((p) => ({ ...p, description: e.target.value }))}
            />
            <input
              className={cn(inputCls, "w-full")}
              placeholder="Install command (e.g. pip install botorch)"
              value={newEntry.install_cmd ?? ""}
              onChange={(e) => setNewEntry((p) => ({ ...p, install_cmd: e.target.value }))}
            />
            <input
              className={cn(inputCls, "w-full")}
              placeholder="Documentation URL"
              value={newEntry.docs_url ?? ""}
              onChange={(e) => setNewEntry((p) => ({ ...p, docs_url: e.target.value }))}
            />
            <div className="flex gap-2">
              <button
                onClick={handleAddEntry}
                disabled={!newEntry.name?.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
              >
                <Save size={12} /> Add
              </button>
              <button
                onClick={() => setShowAdd(false)}
                className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Library Tab ───────────────────────────────────────────────────────────────

function LibraryTab() {
  const sessionId    = useMaestroStore((s) => s.sessionId);
  const refreshState = useMaestroStore((s) => s.refreshState);
  const [library,   setLibrary]   = useState<DocumentLibraryEntry[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading,   setLoading]   = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.listLibrary().then((res) => {
      setLibrary(res.documents);
      setLoading(false);
    });
  }, []);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !sessionId) return;
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      const res = await api.listLibrary();
      setLibrary(res.documents);
      await refreshState();
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleRemove = async (documentId: string) => {
    await api.removeFromLibrary(documentId);
    setLibrary((prev) => prev.filter((d) => d.document_id !== documentId));
  };

  const papers  = library.filter((d) => d.doc_type === "paper");
  const manuals = library.filter((d) => d.doc_type === "manual");

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="glass-panel p-4 space-y-3">
        <h3 className="text-sm font-semibold text-slate-700">Upload Document</h3>
        <p className="text-xs text-slate-500">
          Documents uploaded here are available to MAESTRO across all sessions
          for question answering and campaign extraction.
        </p>
        <div className="flex items-center gap-3">
          <input ref={fileRef} type="file" accept=".pdf" className="hidden" onChange={handleUpload} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
          >
            {uploading ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
            {uploading ? "Uploading..." : "Upload PDF"}
          </button>
          {!sessionId && (
            <span className="text-xs text-amber-600">Start a session on the Dashboard first.</span>
          )}
        </div>
      </div>

      <DocumentSection
        title="Scientific Papers"
        icon="📄"
        documents={papers}
        loading={loading}
        onRemove={handleRemove}
        emptyMessage="No papers uploaded. Upload research papers for MAESTRO to reference."
      />

      <DocumentSection
        title="Equipment Manuals"
        icon="📋"
        documents={manuals}
        loading={loading}
        onRemove={handleRemove}
        emptyMessage="No manuals uploaded. Upload instrument manuals for MAESTRO to reference."
      />
    </div>
  );
}

function DocumentSection({
  title, icon, documents, loading, onRemove, emptyMessage,
}: {
  title:        string;
  icon:         string;
  documents:    DocumentLibraryEntry[];
  loading:      boolean;
  onRemove:     (id: string) => void;
  emptyMessage: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span>{icon}</span>
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
          {documents.length}
        </span>
      </div>
      {loading ? (
        <div className="flex items-center justify-center h-16">
          <Loader2 size={16} className="animate-spin text-blue-500" />
        </div>
      ) : documents.length === 0 ? (
        <div className="glass-panel p-4 text-center text-slate-400 text-xs">{emptyMessage}</div>
      ) : (
        <div className="space-y-2">
          {documents.map((doc) => (
            <div key={doc.document_id} className="glass-panel px-4 py-3 flex items-start gap-3">
              <FileText size={14} className="text-slate-400 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-700 truncate">
                  {doc.title || doc.filename}
                </div>
                {doc.summary && (
                  <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">{doc.summary}</div>
                )}
                <div className="text-[10px] text-slate-400 mt-1">
                  Parsed with MinerU · {doc.uploaded_at?.split("T")[0]}
                </div>
              </div>
              <button
                onClick={() => onRemove(doc.document_id)}
                className="text-slate-400 hover:text-red-500 transition-colors p-1 shrink-0"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Settings Tab ──────────────────────────────────────────────────────────────

function SettingsTab() {
  const labSettings     = useMaestroStore((s) => s.labSettings);
  const loadLabSettings = useMaestroStore((s) => s.loadLabSettings);
  const saveLabSettings = useMaestroStore((s) => s.saveLabSettings);

  const [form,   setForm]   = useState<Partial<LabSettings>>({});
  const [saving, setSaving] = useState(false);
  const [saved,  setSaved]  = useState(false);

  useEffect(() => {
    if (!labSettings) {
      loadLabSettings();
    } else {
      setForm(labSettings);
    }
  }, [labSettings, loadLabSettings]);

  const update = (field: keyof LabSettings, value: unknown) =>
    setForm((f) => ({ ...f, [field]: value }));

  const handleSave = async () => {
    setSaving(true);
    await saveLabSettings(form);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const inputCls = cn(
    "w-full rounded-md px-2 py-1.5 text-xs",
    "bg-white border border-slate-300 text-slate-800",
    "focus:outline-none focus:border-blue-400",
  );

  // Consistent section header style matching all other tabs
  const sectionHeaderCls = "text-sm font-semibold text-slate-700";

  if (!labSettings) {
    return (
      <div className="flex items-center gap-2 text-slate-400">
        <Loader2 size={14} className="animate-spin" />
        Loading settings...
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">

      <div className="glass-panel p-4 space-y-3">
        <h3 className={sectionHeaderCls}>Lab identity</h3>
        <div>
          <label className="text-[10px] text-slate-500 block mb-1">Lab name</label>
          <input
            className={inputCls}
            value={form.lab_name ?? ""}
            onChange={(e) => update("lab_name", e.target.value)}
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 block mb-1">Description</label>
          <input
            className={inputCls}
            value={form.lab_description ?? ""}
            onChange={(e) => update("lab_description", e.target.value)}
          />
        </div>
      </div>

      <div className="glass-panel p-4 space-y-3">
        <h3 className={sectionHeaderCls}>Agent context</h3>
        <p className="text-xs text-slate-500">
          This text is injected into MAESTRO's system prompt. Describe your lab's
          domain, research goals, safety constraints, or resource limits.
          MAESTRO will use this to inform all decisions and recommendations.
        </p>
        <textarea
          className={cn(inputCls, "resize-none")}
          rows={6}
          placeholder={
            "Example:\n" +
            "This lab focuses on battery electrode optimisation.\n" +
            "Safety: no samples above 200°C without prior approval.\n" +
            "Resource target: complete campaigns within 2 lab days.\n" +
            "Equipment manual: see 'Potentiostat Manual' in Library for operating limits."
          }
          value={form.system_prompt_extension ?? ""}
          onChange={(e) => update("system_prompt_extension", e.target.value)}
        />
        <p className="text-[10px] text-slate-400">
          Tip: Upload equipment manuals to the Library tab and reference them here
          so MAESTRO can enforce operating limits automatically.
        </p>
      </div>

      <button
        onClick={handleSave}
        disabled={saving}
        className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
      >
        {saving ? <Loader2 size={12} className="animate-spin" /> :
         saved  ? <CheckCircle2 size={12} /> :
                  <Save size={12} />}
        {saving ? "Saving..." : saved ? "Saved!" : "Save settings"}
      </button>
    </div>
  );
}