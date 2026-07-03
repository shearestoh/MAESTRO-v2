import { useMemo, useCallback, useEffect } from "react";
import {
  ReactFlow, Background, Controls, MiniMap,
  BackgroundVariant, useNodesState, useEdgesState,
  addEdge, type Connection, type Node, type Edge,
  ReactFlowProvider,
} from "@xyflow/react";
import { useMaestroStore } from "@/store/maestroStore";
import { EquipmentNode } from "./EquipmentNode";
import type { EquipmentNodeData, EquipmentStatus } from "@/types";

const nodeTypes = { equipment: EquipmentNode };

function makeNodes(eq: EquipmentStatus): Node[] {
  const defs: Array<{
    id: string; label: string; type: keyof EquipmentStatus | "llm";
    x: number; y: number; desc: string; extra?: Partial<EquipmentNodeData>;
  }> = [
    { id: "maestro",   label: "MAESTRO",   type: "llm",       x: 300, y: 200, desc: "LLM Orchestrator"     },
    { id: "knowledge", label: "Knowledge", type: "knowledge", x:  60, y:  50, desc: "RAG + Document Store"  },
    { id: "optimiser", label: "Optimiser", type: "optimiser", x: 540, y:  50, desc: "Bayesian / LLM-BO"    },
    { id: "sampler",   label: "Sampler",   type: "sampler",   x:  60, y: 360, desc: "Sample Preparation",   extra: { failProb: 0.06, timeCost: 2 } },
    { id: "tester",    label: "Tester",    type: "tester",    x: 540, y: 360, desc: "Characterisation",     extra: { noiseSigma: 0.5, timeCost: 5 } },
    { id: "memory",    label: "Memory",    type: "memory",    x: 300, y: 420, desc: "Experiment Store"      },
    { id: "reporting", label: "Reporting", type: "reporting", x: 300, y:  10, desc: "Figure Generation"     },
  ];

  return defs.map(({ id, label, type, x, y, desc, extra }) => {
    const active = type === "llm" ? eq.llm : eq[type as keyof EquipmentStatus] ?? false;
    return {
      id,
      type: "equipment",
      position: { x, y },
      data: {
        label,
        equipmentType: type === "llm" ? "llm" : type,
        active,
        description: desc,
        status: active ? "active" : "idle",
        ...extra,
      } as EquipmentNodeData,
    };
  });
}

const INITIAL_EDGES: Edge[] = [
  { id: "e-m-k",   source: "maestro",   target: "knowledge" },
  { id: "e-m-o",   source: "maestro",   target: "optimiser" },
  { id: "e-m-s",   source: "maestro",   target: "sampler"   },
  { id: "e-m-t",   source: "maestro",   target: "tester"    },
  { id: "e-m-mem", source: "maestro",   target: "memory"    },
  { id: "e-m-r",   source: "maestro",   target: "reporting" },
  { id: "e-s-t",   source: "sampler",   target: "tester"    },
  { id: "e-t-mem", source: "tester",    target: "memory"    },
];

function LabCanvasInner() {
  const state = useMaestroStore((s) => s.state);
  const eq: EquipmentStatus = state?.equipment_status ?? {
    llm: false, optimiser: false, sampler: false,
    tester: false, memory: false, knowledge: false, reporting: false,
  };

  const [nodes, setNodes, onNodesChange] = useNodesState(makeNodes(eq));
  const [edges, setEdges, onEdgesChange] = useEdgesState(INITIAL_EDGES);

  useEffect(() => {
    setNodes(makeNodes(eq));
    setEdges((eds) =>
      eds.map((e) => {
        const nonMaestroId     = e.source === "maestro" ? e.target : e.source;
        const nonMaestroActive = eq[nonMaestroId as keyof EquipmentStatus] ?? false;
        const isMaestroEdge    = e.source === "maestro" || e.target === "maestro";
        const pipelineActive   =
          (eq[e.source as keyof EquipmentStatus] ?? false) ||
          (eq[e.target as keyof EquipmentStatus] ?? false);
        const animated = isMaestroEdge ? nonMaestroActive : pipelineActive;
        return {
          ...e,
          animated,
          style: { stroke: animated ? "#3b82f6" : "#334155", strokeWidth: animated ? 2 : 1 },
        };
      })
    );
  }, [eq.llm, eq.optimiser, eq.sampler, eq.tester, eq.memory, eq.knowledge, eq.reporting]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  return (
    <div className="w-full h-full rounded-xl overflow-hidden border border-slate-200">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        colorMode="light"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => ((n.data as EquipmentNodeData).active ? "#3b82f6" : "#cbd5e1")}
          maskColor="rgba(248,250,252,0.7)"
          style={{ background: "#f8fafc", border: "1px solid #e2e8f0" }}
        />
      </ReactFlow>
    </div>
  );
}

export function LabCanvas() {
  return (
    <ReactFlowProvider>
      <LabCanvasInner />
    </ReactFlowProvider>
  );
}