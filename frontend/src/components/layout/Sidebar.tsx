import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useMaestroStore } from "@/store/maestroStore";
import {
  LayoutDashboard, FlaskConical, BarChart3,
  ChevronLeft, ChevronRight, Wifi, WifiOff, RotateCcw,
} from "lucide-react";

const navItems = [
  { to: "/",         icon: LayoutDashboard, label: "Dashboard"   },
  { to: "/lab",      icon: FlaskConical,    label: "Lab Builder"  },
  { to: "/campaign", icon: BarChart3,       label: "Campaign"     },
];

export function Sidebar() {
  const open        = useMaestroStore((s) => s.sidebarOpen);
  const setOpen     = useMaestroStore((s) => s.setSidebarOpen);
  const wsConnected = useMaestroStore((s) => s.wsConnected);
  const state       = useMaestroStore((s) => s.state);
  const reset       = useMaestroStore((s) => s.reset);
  const bgActive    = state?.background_job_active ?? false;
  const isLoading   = useMaestroStore((s) => s.isLoading);

  return (
    <aside className={cn(
      "flex flex-col h-full bg-slate-900 border-r border-slate-700",
      "transition-all duration-300 shrink-0",
      open ? "w-56" : "w-14",
    )}>

      {/* ── Logo + Branding ── */}
      <div className="flex items-center gap-3 px-3 py-4 border-b border-slate-700 min-h-[60px]">
        {/* Battery icon as logo */}
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center shrink-0 text-white font-black text-sm select-none">
          ⚡
        </div>
        {open && (
          <div className="min-w-0">
            <div className="font-black text-sm text-slate-100 tracking-wide">
              MAESTRO
            </div>
            <div className="text-[8px] text-slate-500 leading-tight">
              Materials Acceleration Engine for<br />
              Testing, Research &amp; Orchestration
            </div>
          </div>
        )}
      </div>

      {/* ── Nav ── */}
      <nav className="flex-1 p-2 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) => cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
              isActive
                ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200",
            )}
          >
            <Icon size={16} className="shrink-0" />
            {open && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* ── Bottom ── */}
      <div className="p-3 border-t border-slate-700 space-y-2">

        {/* WS status */}
        <div className={cn(
          "flex items-center gap-2 px-2 py-1 rounded-lg text-xs",
          wsConnected ? "text-green-400" : "text-slate-500",
        )}>
          {wsConnected
            ? <Wifi size={11} />
            : <WifiOff size={11} />}
          {open && (
            <span>{wsConnected ? "Live" : "Polling"}</span>
          )}
        </div>

        {/* Day indicator */}
        {state && open && (
          <div className="text-xs text-slate-500 px-2">
            Day {state.virtual_day_index}
          </div>
        )}

        {/* Reset — moved here from TopBar */}
        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          title="Reset session"
          className={cn(
            "w-full flex items-center gap-2 px-2 py-1.5 rounded-lg",
            "text-xs text-red-400/60 hover:text-red-400 hover:bg-red-500/10",
            "transition-colors disabled:opacity-30",
          )}
        >
          <RotateCcw size={11} className="shrink-0" />
          {open && <span>Reset session</span>}
        </button>

        {/* Collapse toggle */}
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-center p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          {open ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
        </button>
      </div>
    </aside>
  );
}