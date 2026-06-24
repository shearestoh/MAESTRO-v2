import { useCallback, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { EquipmentNode } from "@/components/digital-twin/EquipmentNode";
import type { EquipmentNodeData, EquipmentType } from "@/types";
import { cn } from "@/lib/utils";

const nodeTypes = { equipment: EquipmentNode };

// ── Equipment palette definition ──────────────────────────────────────────────

const PALETTE: Array<{
  type:  EquipmentType;
  label: string;
  icon:  string;
  desc:  string;
  extra: Partial<EquipmentNodeData>;
}> = [
  { type: "sampler",   label: "Sampler",   icon: "🧪", desc: "Sample preparation",  extra: { failProb: 0.06, timeCost: 2  } },
  { type: "tester",    label: "Tester",    icon: "⚡", desc: "Electrochemical test", extra: { noiseSigma: 0.5, timeCost: 5 } },
  { type: "optimiser", label: "Optimiser", icon: "📈", desc: "BO / LLM-BO engine",  extra: {} },
  { type: "memory",    label: "Memory",    icon: "💾", desc: "Experiment data store",extra: {} },
  { type: "knowledge", label: "Knowledge", icon: "📚", desc: "RAG document store",  extra: {} },
  { type: "reporting", label: "Reporting", icon: "📊", desc: "Figure generator",    extra: {} },
  { type: "custom",    label: "Custom",    icon: "⚙️", desc: "User-defined",        extra: {} },
];

let idCtr = 100;

// ── Inner canvas (needs ReactFlowProvider above it) ───────────────────────────

function LabBuilderInner() {
  // ✅ Explicit generics tell TypeScript the exact shape of nodes and edges
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<EquipmentNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const { screenToFlowPosition } = useReactFlow();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const type = e.dataTransfer.getData("maestro/equipment") as EquipmentType;
      const item  = PALETTE.find((p) => p.type === type);
      if (!item) return;

      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });

      const newNode: Node<EquipmentNodeData> = {
        id:       `eq_${idCtr++}`,
        type:     "equipment",
        position,
        data: {
          label:         item.label,
          equipmentType: item.type,
          active:        false,
          description:   item.desc,
          status:        "idle",
          ...item.extra,
        },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [screenToFlowPosition, setNodes]
  );

  // ✅ Typed as Node<EquipmentNodeData> | undefined — no more 'never'
  const selected: Node<EquipmentNodeData> | undefined = nodes.find(
    (n) => n.id === selectedId
  );

  return (
    <div className="flex h-full gap-4 p-4">

      {/* ── Equipment palette ── */}
      <div className="w-52 shrink-0 glass-panel p-4 space-y-3 overflow-y-auto">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Equipment Library
        </div>
        <div className="text-xs text-slate-600">Drag onto canvas</div>

        <div className="space-y-2">
          {PALETTE.map((item) => (
            <div
              key={item.type}
              draggable
              onDragStart={(e) =>
                e.dataTransfer.setData("maestro/equipment", item.type)
              }
              className="flex items-center gap-3 p-2.5 rounded-lg border border-slate-700 bg-slate-800 hover:border-blue-500 hover:bg-blue-500/5 cursor-grab active:cursor-grabbing transition-colors"
            >
              <span className="text-xl">{item.icon}</span>
              <div>
                <div className="text-xs font-semibold text-slate-200">{item.label}</div>
                <div className="text-[10px] text-slate-500">{item.desc}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Lab constraints reference */}
        <div className="border-t border-slate-700 pt-3 space-y-1.5">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Lab Defaults
          </div>
          {[
            { label: "Time budget", value: "480 min/day" },
            { label: "Base fail %", value: "6%"          },
            { label: "Noise σ",     value: "0.5 Wh/kg"  },
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between text-xs">
              <span className="text-slate-500">{label}</span>
              <span className="text-slate-300 font-mono">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── React Flow canvas ── */}
      <div className="flex-1 rounded-xl overflow-hidden border border-slate-700">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onPaneClick={() => setSelectedId(null)}
          nodeTypes={nodeTypes}
          fitView
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="#1e293b"
          />
          <Controls />
        </ReactFlow>
      </div>

      {/* ── Properties panel ── */}
      <div className="w-52 shrink-0 glass-panel p-4 space-y-3">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Properties
        </div>

        {!selected ? (
          <div className="text-xs text-slate-600 italic">
            Click a node to inspect.
          </div>
        ) : (
          <div className="space-y-2 text-xs">
            {/* Node ID */}
            <div className="flex justify-between">
              <span className="text-slate-500">id</span>
              <span className="text-slate-300 font-mono truncate max-w-[100px]">
                {selected.id}
              </span>
            </div>

            {/* All data fields */}
            {(
              Object.entries(selected.data) as [string, unknown][]
            )
              .filter(([k]) => k !== "label")
              .map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <span className="text-slate-500 shrink-0">{k}</span>
                  <span className="text-slate-300 font-mono text-right truncate">
                    {String(v)}
                  </span>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Public export (wraps inner with ReactFlowProvider) ────────────────────────

export function LabBuilder() {
  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-slate-700 shrink-0">
        <h1 className="text-lg font-bold text-slate-100">Lab Builder</h1>
        <p className="text-xs text-slate-500">
          Drag equipment onto the canvas to design your virtual lab topology.
          Connect nodes to define the experimental workflow.
        </p>
      </div>
      <div className="flex-1 min-h-0">
        <ReactFlowProvider>
          <LabBuilderInner />
        </ReactFlowProvider>
      </div>
    </div>
  );
}