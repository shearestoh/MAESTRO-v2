import { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow, Background, Controls, MiniMap,
  BackgroundVariant, useNodesState, useEdgesState,
  addEdge, type Connection, type Node, type Edge,
  ReactFlowProvider,
} from "@xyflow/react";
import { useMaestroStore } from "@/store/maestroStore";
import { EquipmentNode }   from "./EquipmentNode";
import type { EquipmentNodeData, EquipmentStatus } from "@/types";

const nodeTypes = { equipment: EquipmentNode };

const INITIAL_EDGES: Edge[] = [
  { id: "e-m-k",   source: "maestro",       target: "knowledge"     },
  { id: "e-m-o",   source: "maestro",       target: "optimiser"     },
  { id: "e-m-s",   source: "maestro",       target: "synthesiser"   },
  { id: "e-m-t",   source: "maestro",       target: "characteriser" },
  { id: "e-m-mem", source: "maestro",       target: "memory"        },
  { id: "e-m-r",   source: "maestro",       target: "reporting"     },
  { id: "e-s-t",   source: "synthesiser",   target: "characteriser" },
  { id: "e-t-mem", source: "characteriser", target: "memory"        },
];

const NODE_DEFS: Array<{
  id:    string;
  label: string;
  eqKey: keyof EquipmentStatus | "llm";
  x:     number;
  y:     number;
  desc:  string;
  extra?: Partial<EquipmentNodeData>;
}> = [
  { id: "maestro",       label: "MAESTRO",       eqKey: "llm",           x: 300, y: 200, desc: "LLM Orchestrator"     },
  { id: "knowledge",     label: "Knowledge",     eqKey: "knowledge",     x:  60, y:  50, desc: "RAG + Document Store" },
  { id: "optimiser",     label: "Optimiser",     eqKey: "optimiser",     x: 540, y:  50, desc: "Bayesian / LLM-BO"   },
  { id: "synthesiser",   label: "Synthesiser",   eqKey: "synthesiser",   x:  60, y: 360, desc: "Sample Synthesis",    extra: { failProb: 0.06, timeCostS: 5  } },
  { id: "characteriser", label: "Characteriser", eqKey: "characteriser", x: 540, y: 360, desc: "Characterisation",    extra: { noiseSigma: 0.5, timeCostS: 8 } },
  { id: "memory",        label: "Memory",        eqKey: "memory",        x: 300, y: 420, desc: "Experiment Store"     },
  { id: "reporting",     label: "Reporting",     eqKey: "reporting",     x: 300, y:  10, desc: "Figure Generation"    },
];

function buildNodes(eq: EquipmentStatus): Node[] {
  return NODE_DEFS.map(({ id, label, eqKey, x, y, desc, extra }) => {
    const active = eqKey === "llm" ? eq.llm : eq[eqKey as keyof EquipmentStatus];
    return {
      id,
      type: "equipment",
      position: { x, y },
      data: {
        label,
        equipmentType: eqKey === "llm" ? "llm" : eqKey,
        active,
        description: desc,
        status: active ? "active" : "idle",
        ...extra,
      } as EquipmentNodeData,
    };
  });
}

function buildEdges(eq: EquipmentStatus): Edge[] {
  return INITIAL_EDGES.map((e) => {
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
  });
}

function LabCanvasInner() {
  const eq: EquipmentStatus = useMaestroStore((s) => s.state?.equipment_status ?? {
    llm: false, optimiser: false, synthesiser: false,
    characteriser: false, memory: false, knowledge: false, reporting: false,
  });

  const initialNodes = useMemo(() => buildNodes(eq), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(buildEdges(eq));

  // Stable change key — only re-render when a flag actually flips
  const eqKey = NODE_DEFS.map(({ eqKey }) =>
    eqKey === "llm" ? Number(eq.llm) : Number(eq[eqKey as keyof EquipmentStatus])
  ).join("");

  useEffect(() => {
    setNodes(buildNodes(eq));
    setEdges(buildEdges(eq));
  }, [eqKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
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