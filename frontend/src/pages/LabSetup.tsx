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
  OptimisationLibraryEntry, DocumentLibraryEntry,
  LabResource, ProtocolEntry,
} from "@/types";

type Tab = "instruments" | "optimisation" | "library" | "resources" | "settings";

export function LabSetup() {
  const [tab, setTab] = useState<Tab>("instruments");

  const tabs: { id: Tab; label: string }[] = [
    { id: "instruments",  label: "Instruments"  },
    { id: "optimisation", label: "Optimisation" },
    { id: "library",      label: "Library"      },
    { id: "resources",    label: "Resources"    },
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
        {tab === "resources"    && <ResourcesTab />}
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
    synthesis:       "🧪",
    characterisation:"⚡",
    simulation:      "💻",
    modelling:       "🧮",
    data:            "💾",
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
        {instrument.time_cost_s > 0 && (
          <span className="text-[10px] text-slate-400">{instrument.time_cost_s}s</span>
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
  const [timeCostS,   setTimeCostS]   = useState(String(initial?.time_cost_s ?? 5));
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
      time_cost_s: parseFloat(timeCostS) || 0,
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
          <input className={inputCls} type="number" value={timeCostS} onChange={(e) => setTimeCostS(e.target.value)} min="0" />
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
          for each task. Built-in libraries (scikit-optimize GP-BO and Random Search)
          are always available. Optional libraries require separate installation.
        </p>
        <div className="space-y-3">
          {optimisationLibrary.map((lib) => (
            <div key={lib.lib_id} className="glass-panel p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{lib.name}</span>
                    {lib.is_default && (
                      <span className="text-[9px] text-green-600 bg-green-50 px-1 py-0.5 rounded">built-in</span>
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
          for question answering and campaign extraction. Authors, year, DOI,
          and journal are automatically extracted.
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
        emptyMessage="No manuals uploaded. Upload instrument manuals for MAESTRO to reference safety limits."
      />

      <ProtocolsSection />
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
        <h3 className="text-sm font-semibold text-slate-700">Lab identity</h3>
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
        <h3 className="text-sm font-semibold text-slate-700">Agent context</h3>
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


// ── Resources Tab ─────────────────────────────────────────────────────────────

function ResourcesTab() {
  const [resources, setResources] = useState<LabResource[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [showForm,  setShowForm]  = useState(false);

  useEffect(() => {
    api.listResources().then((res) => {
      setResources(res.resources);
      setLoading(false);
    });
  }, []);

  const handleDelete = async (resourceId: string) => {
    await api.deleteResource(resourceId);
    setResources((prev) => prev.filter((r) => r.resource_id !== resourceId));
  };

  const handleStockUpdate = async (resourceId: string, delta: number) => {
    const resource = resources.find((r) => r.resource_id === resourceId);
    if (!resource) return;
    const newStock = Math.max(0, resource.current_stock + delta);
    const updated  = await api.updateResource(resourceId, { current_stock: newStock });
    setResources((prev) =>
      prev.map((r) => r.resource_id === resourceId ? updated.resource : r)
    );
  };

  const handleSaved = (resource: LabResource) => {
    setResources((prev) => {
      const idx = prev.findIndex((r) => r.resource_id === resource.resource_id);
      if (idx >= 0) {
        const next = [...prev]; next[idx] = resource; return next;
      }
      return [...prev, resource];
    });
    setShowForm(false);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-slate-400">
        <Loader2 size={14} className="animate-spin" /> Loading resources...
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-1">Consumables inventory</h3>
        <p className="text-xs text-slate-500 mb-4">
          Track lab consumables (chemicals, cell casings, substrates, etc.) and define
          how much each instrument consumes per operation. MAESTRO will deduct stock
          automatically and alert you when supplies run low.
        </p>

        <div className="flex justify-end mb-3">
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors"
          >
            <Plus size={12} /> Add Resource
          </button>
        </div>

        {resources.length === 0 ? (
          <div className="glass-panel p-8 text-center text-slate-400 text-xs">
            No resources registered. Add consumables to track inventory.
          </div>
        ) : (
          <div className="space-y-3">
            {resources.map((r) => {
              const isLow = r.min_stock > 0 && r.current_stock <= r.min_stock;
              return (
                <div key={r.resource_id} className={cn(
                  "glass-panel p-4 space-y-3",
                  isLow && "border-amber-300 border"
                )}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800">{r.name}</span>
                        {isLow && (
                          <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded font-medium">
                            Low stock
                          </span>
                        )}
                      </div>
                      {r.description && (
                        <p className="text-xs text-slate-500 mt-0.5">{r.description}</p>
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(r.resource_id)}
                      className="text-slate-400 hover:text-red-500 transition-colors p-1 shrink-0"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>

                  {/* Stock level */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                        <span>Current stock</span>
                        <span className={isLow ? "text-amber-600 font-semibold" : ""}>
                          {r.current_stock.toFixed(1)} {r.unit}
                          {r.min_stock > 0 && ` (min: ${r.min_stock} ${r.unit})`}
                        </span>
                      </div>
                      {r.min_stock > 0 && (
                        <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                          <div
                            className={cn(
                              "h-full rounded-full transition-all",
                              isLow ? "bg-amber-400" : "bg-green-500"
                            )}
                            style={{
                              width: `${Math.min(100, (r.current_stock / (r.min_stock * 5)) * 100)}%`,
                            }}
                          />
                        </div>
                      )}
                    </div>
                    {/* Quick stock adjustment */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleStockUpdate(r.resource_id, -1)}
                        className="w-6 h-6 rounded bg-slate-100 text-slate-600 hover:bg-slate-200 text-xs font-bold transition-colors"
                        title="Remove 1 unit"
                      >−</button>
                      <button
                        onClick={() => handleStockUpdate(r.resource_id, 10)}
                        className="px-2 h-6 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 text-xs font-medium transition-colors"
                        title="Add 10 units"
                      >+10</button>
                    </div>
                  </div>

                  {/* Consumption rules */}
                  {r.consumption_rules.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                        Consumed by
                      </div>
                      {r.consumption_rules.map((rule, i) => (
                        <div key={i} className="flex justify-between text-xs text-slate-500">
                          <span>{rule.instrument_name}</span>
                          <span className="font-mono text-slate-400">
                            {rule.amount_per_use} {r.unit} / use
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {showForm && (
          <ResourceForm
            onSaved={handleSaved}
            onCancel={() => setShowForm(false)}
          />
        )}
      </div>
    </div>
  );
}

function ResourceForm({
  onSaved,
  onCancel,
}: {
  onSaved:  (r: LabResource) => void;
  onCancel: () => void;
}) {
  const [name,        setName]        = useState("");
  const [unit,        setUnit]        = useState("");
  const [stock,       setStock]       = useState("0");
  const [minStock,    setMinStock]    = useState("0");
  const [description, setDescription] = useState("");
  const [rules,       setRules]       = useState<
    Array<{ instrument_name: string; amount_per_use: string; description: string }>
  >([]);
  const [saving, setSaving] = useState(false);

  const addRule = () =>
    setRules((r) => [...r, { instrument_name: "", amount_per_use: "1", description: "" }]);

  const updateRule = (i: number, field: string, val: string) =>
    setRules((r) => r.map((x, j) => j === i ? { ...x, [field]: val } : x));

  const handleSave = async () => {
    if (!name.trim() || !unit.trim()) return;
    setSaving(true);
    try {
      const result = await api.addResource({
        name,
        unit,
        current_stock: parseFloat(stock) || 0,
        min_stock:     parseFloat(minStock) || 0,
        description,
        consumption_rules: rules
          .filter((r) => r.instrument_name.trim())
          .map((r) => ({
            instrument_name: r.instrument_name.trim(),
            amount_per_use:  parseFloat(r.amount_per_use) || 1,
            description:     r.description,
          })),
      });
      onSaved(result.resource);
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
    <div className="glass-panel p-5 space-y-4 border-blue-200 border mt-4">
      <h3 className="text-sm font-semibold text-slate-700">Add Resource</h3>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Name</label>
          <input
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. NMC Slurry, Coin Cell Casing"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Unit</label>
          <input
            className={inputCls}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="e.g. mL, units, g"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
            Current stock
          </label>
          <input
            className={inputCls}
            type="number"
            value={stock}
            onChange={(e) => setStock(e.target.value)}
            min="0" step="0.1"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
            Minimum stock (alert threshold)
          </label>
          <input
            className={inputCls}
            type="number"
            value={minStock}
            onChange={(e) => setMinStock(e.target.value)}
            min="0" step="0.1"
          />
        </div>
      </div>

      <div>
        <label className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
          Description
        </label>
        <input
          className={inputCls}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. NMC cathode slurry for electrode coating"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">
            Consumption rules
          </label>
          <button onClick={addRule} className="text-[10px] text-blue-600 hover:underline">
            + Add rule
          </button>
        </div>
        <p className="text-[10px] text-slate-400 mb-2">
          Define how much of this resource each instrument consumes per operation.
          MAESTRO will deduct stock automatically when that instrument is used.
        </p>
        {rules.map((rule, i) => (
          <div key={i} className="grid grid-cols-3 gap-1.5 mb-1.5">
            <input
              className={inputCls}
              placeholder="Instrument name"
              value={rule.instrument_name}
              onChange={(e) => updateRule(i, "instrument_name", e.target.value)}
            />
            <input
              className={inputCls}
              placeholder={`Amount per use (${unit || "units"})`}
              type="number"
              value={rule.amount_per_use}
              onChange={(e) => updateRule(i, "amount_per_use", e.target.value)}
              min="0" step="0.1"
            />
            <button
              onClick={() => setRules((r) => r.filter((_, j) => j !== i))}
              className="text-red-400 hover:text-red-600 text-xs"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !name.trim() || !unit.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {saving ? "Saving..." : "Save Resource"}
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


// ── Protocols Section ────────────────────────────────────

function ProtocolsSection() {
  const state     = useMaestroStore((s) => s.state);
  const sessionId = useMaestroStore((s) => s.sessionId);

  const [protocols, setProtocols] = useState<ProtocolEntry[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [showSave,  setShowSave]  = useState(false);
  const [saveName,  setSaveName]  = useState("");
  const [saveDesc,  setSaveDesc]  = useState("");
  const [saveNotes, setSaveNotes] = useState("");
  const [saving,    setSaving]    = useState(false);

  useEffect(() => {
    api.listProtocols().then((res) => {
      setProtocols(res.protocols);
      setLoading(false);
    });
  }, []);

  const handleSaveProtocol = async () => {
    if (!saveName.trim()) return;
    setSaving(true);
    try {
      const userInstructions = (state?.messages ?? [])
        .filter((m) => m.role === "user")
        .map((m) => m.content)
        .slice(-10);

      const workflowPlan = state?.background_job_plan?.length
        ? { steps: state.background_job_plan, summary: "Captured workflow" }
        : null;

      const results = state?.results_store ?? [];
      const resultsSummary = results.length > 0
        ? results.map((r) =>
            `${r.condition_label}=${r.condition_value}` +
            (r.optimiser_name ? ` [${r.optimiser_name}]` : "") +
            `: best=${r.best_objective !== null ? r.best_objective.toFixed(4) : "N/A"}` +
            `, n=${r.X.length}`
          ).join("; ")
        : "No results recorded";

      const optimiserUsed = [
        ...new Set(results.map((r) => r.optimiser_name || "").filter(Boolean)),
      ].join(", ");

      const result = await api.saveProtocol({
        name:              saveName,
        description:       saveDesc,
        notes:             saveNotes,
        user_instructions: userInstructions,
        workflow_plan:     workflowPlan as Record<string, unknown> | null,
        results_summary:   resultsSummary,
        optimiser_used:    optimiserUsed,
        tags:              [],
      });
      setProtocols((prev) => [...prev, result.protocol]);
      setShowSave(false);
      setSaveName(""); setSaveDesc(""); setSaveNotes("");
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (protocolId: string) => {
    await api.deleteProtocol(protocolId);
    setProtocols((prev) => prev.filter((p) => p.protocol_id !== protocolId));
  };

  const handleLoadToChat = (protocol: ProtocolEntry) => {
    const prompt = [
      `[Replaying protocol: "${protocol.name}"]`,
      ``,
      `Previous instructions from this protocol:`,
      ...protocol.user_instructions.map((instr, i) => `${i + 1}. ${instr}`),
      ``,
      `Please replay this workflow. You may modify parameters, optimiser, or conditions as needed.`,
    ].join("\n");
    navigator.clipboard.writeText(prompt).then(() => {
      alert(
        `Protocol context copied to clipboard.\n\nPaste it into the chat on the Dashboard to replay or adapt this workflow.`
      );
    });
  };

  const inputCls = cn(
    "w-full rounded-md px-2 py-1.5 text-xs",
    "bg-white border border-slate-300 text-slate-800",
    "focus:outline-none focus:border-blue-400",
  );

  return (
    <div className="mt-8 border-t border-slate-100 pt-6">
      <div className="flex items-center gap-2 mb-3">
        <span>📋</span>
        <h3 className="text-sm font-semibold text-slate-700">Protocols</h3>
        <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
          {protocols.length}
        </span>
      </div>

      <p className="text-xs text-slate-500 mb-4">
        Save the current session as a reusable protocol — a reproducible record of the
        instructions and workflow that MAESTRO executed. Another scientist can load a
        protocol into the chat to replay or adapt the same experimental sequence.
      </p>

      {/* Save current session */}
      {sessionId && (
        <button
          onClick={() => setShowSave(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors mb-4"
        >
          <Save size={12} /> Save current session as protocol
        </button>
      )}

      {showSave && (
        <div className="glass-panel p-4 space-y-3 border-blue-200 border mb-4">
          <h4 className="text-sm font-semibold text-slate-700">Save protocol</h4>
          <input
            className={inputCls}
            placeholder="Protocol name (e.g. GP-BO cathode optimisation — week 1)"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
          />
          <input
            className={inputCls}
            placeholder="Description (optional)"
            value={saveDesc}
            onChange={(e) => setSaveDesc(e.target.value)}
          />
          <textarea
            className={cn(inputCls, "resize-none")}
            rows={2}
            placeholder="Notes (e.g. conditions used, observations, suggested next steps)"
            value={saveNotes}
            onChange={(e) => setSaveNotes(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={handleSaveProtocol}
              disabled={saving || !saveName.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-500 transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => { setShowSave(false); setSaveName(""); setSaveDesc(""); setSaveNotes(""); }}
              className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 text-xs">
          <Loader2 size={14} className="animate-spin" /> Loading protocols...
        </div>
      ) : protocols.length === 0 ? (
        <div className="glass-panel p-4 text-center text-slate-400 text-xs">
          No protocols saved yet. Run an experiment and save it as a protocol above.
        </div>
      ) : (
        <div className="space-y-2">
          {protocols.map((p) => (
            <div key={p.protocol_id} className="glass-panel px-4 py-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-slate-700">{p.name}</div>
                  {p.description && (
                    <div className="text-xs text-slate-500 mt-0.5">{p.description}</div>
                  )}
                  <div className="text-[10px] text-slate-400 mt-1 space-y-0.5">
                    {p.created_at && (
                      <div>Saved: {new Date(p.created_at).toLocaleString()}</div>
                    )}
                    {p.optimiser_used && (
                      <div>Optimiser: <span className="text-blue-600">{p.optimiser_used}</span></div>
                    )}
                    {p.results_summary && (
                      <div className="text-green-600 font-medium">{p.results_summary}</div>
                    )}
                    {p.notes && (
                      <div className="italic text-slate-400">{p.notes}</div>
                    )}
                  </div>

                  {p.user_instructions.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-[10px] text-blue-600 cursor-pointer hover:underline">
                        View {p.user_instructions.length} instruction(s)
                      </summary>
                      <div className="mt-1 space-y-0.5 pl-2 border-l border-slate-200">
                        {p.user_instructions.map((instr, i) => (
                          <div key={i} className="text-[10px] text-slate-500">
                            {i + 1}. {instr}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => handleLoadToChat(p)}
                    className="text-[10px] text-blue-600 hover:underline px-2 py-1 rounded hover:bg-blue-50 transition-colors"
                    title="Copy protocol context to clipboard for chat replay"
                  >
                    Load ↗
                  </button>
                  <button
                    onClick={() => handleDelete(p.protocol_id)}
                    className="text-slate-400 hover:text-red-500 transition-colors p-1"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}