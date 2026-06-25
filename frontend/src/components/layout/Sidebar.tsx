import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useMaestroStore } from "@/store/maestroStore";
import {
  LayoutDashboard, FlaskConical, BarChart3,
  ChevronLeft, ChevronRight, Wifi, WifiOff,
} from "lucide-react";

// Reproducibility removed — absorbed into Campaign
const navItems = [
  { to: "/",        icon: LayoutDashboard, label: "Dashboard"  },
  { to: "/lab",     icon: FlaskConical,    label: "Lab Builder" },
  { to: "/campaign",icon: BarChart3,       label: "Campaign"    },
];

export function Sidebar() {
  const open        = useMaestroStore((s) => s.sidebarOpen);
  const setOpen     = useMaestroStore((s) => s.setSidebarOpen);
  const wsConnected = useMaestroStore((s) => s.wsConnected);
  const state       = useMaestroStore((s) => s.state);

  return (
    <aside className={cn(
      "flex flex-col h-full bg-slate-900 border-r border-slate-700 transition-all duration-300 shrink-0",
      open ? "w-52" : "w-14",
    )}>
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-4 border-b border-slate-700 min-h-[60px]">
        <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center text-white font-black text-xs shrink-0">
          M
        </div>
        {open && (
          <div>
            <div className="font-black text-sm text-slate-100 tracking-wide">MAESTRO</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-widest">v3 · Agentic SDL</div>
          </div>
        )}
      </div>

      {/* Nav */}
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

      {/* Bottom */}
      <div className="p-3 border-t border-slate-700 space-y-2">
        <div className={cn(
          "flex items-center gap-2 px-2 py-1 rounded-lg text-xs",
          wsConnected ? "text-green-400" : "text-slate-500",
        )}>
          {wsConnected ? <Wifi size={11} /> : <WifiOff size={11} />}
          {open && <span>{wsConnected ? "Live" : "Polling"}</span>}
        </div>
        {state && open && (
          <div className="text-xs text-slate-500 px-2">Day {state.virtual_day_index}</div>
        )}
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