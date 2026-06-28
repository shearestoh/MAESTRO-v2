import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label:      string;
  value:      string | number;
  sub?:       string;
  icon?:      LucideIcon;
  accent?:    "blue" | "green" | "amber" | "red" | "muted";
  className?: string;
}

const accentStyles = {
  blue:  "text-blue-600  dark:text-blue-400  border-l-blue-500",
  green: "text-green-600 dark:text-green-400 border-l-green-500",
  amber: "text-amber-600 dark:text-amber-400 border-l-amber-500",
  red:   "text-red-600   dark:text-red-400   border-l-red-500",
  muted: "text-slate-500 dark:text-slate-400 border-l-slate-400",
};

export function MetricCard({
  label, value, sub, icon: Icon, accent = "blue", className,
}: MetricCardProps) {
  return (
    <div className={cn(
      "glass-panel p-4 flex flex-col gap-1 border-l-2",
      accentStyles[accent],
      className,
    )}>
      <div className={cn(
        "flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider",
        "text-slate-500 dark:text-slate-400",
      )}>
        {Icon && <Icon size={11} />}
        {label}
      </div>
      <div className="text-2xl font-bold font-mono text-slate-800 dark:text-slate-100">
        {value}
      </div>
      {sub && (
        <div className="text-xs text-slate-500 dark:text-slate-500">{sub}</div>
      )}
    </div>
  );
}