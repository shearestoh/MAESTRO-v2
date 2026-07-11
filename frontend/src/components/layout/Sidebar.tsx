import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useMaestroStore } from "@/store/maestroStore";
import {
  LayoutDashboard, BookOpen, Settings, FlaskConical,
  ChevronLeft, ChevronRight, Wifi, WifiOff, RotateCcw,
} from "lucide-react";

const navItems = [
  { to: "/",         icon: LayoutDashboard, label: "Dashboard"    },
  { to: "/lab",      icon: Settings,        label: "Lab Setup"    },
  { to: "/notebook", icon: BookOpen,        label: "Lab Notebook" },
];

function MaestroLogo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
      <circle cx="16" cy="16" r="16" fill="#2563eb"/>
      <text
        x="16" y="22"
        fontFamily="system-ui, sans-serif"
        fontSize="18"
        fontWeight="900"
        fill="white"
        textAnchor="middle"
      >
        M
      </text>
    </svg>
  );
}

export function Sidebar() {
  const open      = useMaestroStore((s) => s.sidebarOpen);
  const setOpen   = useMaestroStore((s) => s.setSidebarOpen);
  const wsConn    = useMaestroStore((s) => s.wsConnected);
  const state     = useMaestroStore((s) => s.state);
  const reset     = useMaestroStore((s) => s.reset);
  const bgActive  = state?.background_job_active ?? false;
  const isLoading = useMaestroStore((s) => s.isLoading);

  return (
    <aside className={cn(
      "flex flex-col h-full bg-white border-r border-slate-200 transition-all duration-300 shrink-0",
      open ? "w-52" : "w-14",
    )}>
      <div className="flex items-center gap-3 px-3 py-4 min-h-[56px] border-b border-slate-200">
        <MaestroLogo size={32} />
        {open && (
          <span className="font-black text-sm text-slate-800 tracking-wide">MAESTRO</span>
        )}
      </div>

      <nav className="flex-1 p-2 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) => cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
              isActive
                ? "bg-blue-50 text-blue-600 border border-blue-200"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-800",
            )}
          >
            <Icon size={16} className="shrink-0" />
            {open && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t border-slate-200 space-y-2">
        <div className={cn(
          "flex items-center gap-2 px-2 py-1 rounded-lg text-xs",
          wsConn ? "text-green-600" : "text-slate-400",
        )}>
          {wsConn ? <Wifi size={11} /> : <WifiOff size={11} />}
          {open && <span>{wsConn ? "Live" : "Polling"}</span>}
        </div>

        <button
          onClick={reset}
          disabled={bgActive || isLoading}
          title="Reset session"
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-30"
        >
          <RotateCcw size={11} className="shrink-0" />
          {open && <span>Reset session</span>}
        </button>

        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-center p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
        >
          {open ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
        </button>
      </div>
    </aside>
  );
}