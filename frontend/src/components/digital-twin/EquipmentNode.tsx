import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import type { EquipmentNodeData } from "@/types";

const typeConfig: Record<string, { icon: string; border: string; bg: string; glow: string }> = {
  llm:       { icon: "🧠", border: "border-blue-500/60",   bg: "bg-blue-500/10",   glow: "glow-blue"  },
  optimiser: { icon: "📈", border: "border-violet-500/60", bg: "bg-violet-500/10", glow: "glow-blue"  },
  sampler:   { icon: "🧪", border: "border-cyan-500/60",   bg: "bg-cyan-500/10",   glow: "glow-blue"  },
  tester:    { icon: "⚡", border: "border-yellow-500/60", bg: "bg-yellow-500/10", glow: "glow-amber" },
  memory:    { icon: "💾", border: "border-green-500/60",  bg: "bg-green-500/10",  glow: "glow-green" },
  knowledge: { icon: "📚", border: "border-pink-500/60",   bg: "bg-pink-500/10",   glow: "glow-blue"  },
  reporting: { icon: "📊", border: "border-orange-500/60", bg: "bg-orange-500/10", glow: "glow-amber" },
  custom:    { icon: "⚙️", border: "border-slate-600",     bg: "bg-slate-800",     glow: ""           },
};

export const EquipmentNode = memo(function EquipmentNode({ data }: NodeProps) {
  const d   = data as EquipmentNodeData;
  const cfg = typeConfig[d.equipmentType] ?? typeConfig.custom;

  return (
    <div className={cn(
      "relative px-4 py-3 rounded-xl border-2 min-w-[110px] text-center",
      "transition-all duration-300 cursor-default select-none",
      cfg.border, cfg.bg,
      d.active && cfg.glow,
      d.active && "scale-105",
    )}>
      <Handle type="target" position={Position.Top}
        className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom}
        className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />
      <Handle type="target" position={Position.Left}
        className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />
      <Handle type="source" position={Position.Right}
        className="!bg-slate-600 !border-slate-500 !w-2 !h-2" />

      {/* Pulse ring when active */}
      {d.active && (
        <div className="absolute inset-0 rounded-xl border-2 border-blue-400/50 animate-ping pointer-events-none" />
      )}

      <div className="text-2xl mb-1">{cfg.icon}</div>
      <div className="text-xs font-bold text-slate-100">{d.label}</div>
      {d.description && (
        <div className="text-[10px] text-slate-500 mt-0.5">{d.description}</div>
      )}

      <div className="flex justify-center mt-1.5">
        <span className={cn("status-dot", d.active ? "active" : "idle")} />
      </div>

      {(d.failProb !== undefined || d.timeCost !== undefined) && (
        <div className="flex gap-1 justify-center mt-1.5 flex-wrap">
          {d.failProb !== undefined && (
            <span className="text-[9px] bg-red-500/20 text-red-400 px-1 rounded">
              fail {(d.failProb * 100).toFixed(0)}%
            </span>
          )}
          {d.timeCost !== undefined && (
            <span className="text-[9px] bg-blue-500/20 text-blue-400 px-1 rounded">
              {d.timeCost}min
            </span>
          )}
        </div>
      )}
    </div>
  );
});