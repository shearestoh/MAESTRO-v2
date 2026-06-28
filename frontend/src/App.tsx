import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect }          from "react";
import { Sidebar }            from "@/components/layout/Sidebar";
import { TopBar }             from "@/components/layout/TopBar";
import { Dashboard }          from "@/pages/Dashboard";
import { LabBuilder }         from "@/pages/LabBuilder";
import { LabNotebook }        from "@/pages/LabNotebook";
import { useMaestroStore }    from "@/store/maestroStore";
import { useWebSocket }       from "@/hooks/useWebSocket";
import { usePolling }         from "@/hooks/usePolling";
import { Loader2 }            from "lucide-react";

function AppShell() {
  useWebSocket();
  usePolling();

  const isBooting = useMaestroStore((s) => s.isLoading && !s.state);
  const error     = useMaestroStore((s) => s.error);
  const clearErr  = useMaestroStore((s) => s.clearError);
  const theme     = useMaestroStore((s) => s.theme);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  if (isBooting) {
    return (
      <div className="flex h-screen items-center justify-center bg-white dark:bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center">
            <Loader2 size={24} className="text-white animate-spin" />
          </div>
          <div className="text-sm text-slate-500">Connecting to MAESTRO...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-950">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar />
        {error && (
          <div className="bg-red-50 dark:bg-red-500/10 border-b border-red-200 dark:border-red-500/30 px-4 py-2 flex items-center justify-between shrink-0">
            <span className="text-xs text-red-600 dark:text-red-400">{error}</span>
            <button
              onClick={clearErr}
              className="text-xs text-red-500 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}
        <main className="flex-1 min-h-0 overflow-hidden">
          <Routes>
            <Route path="/"            index element={<Dashboard />} />
            <Route path="/lab"         element={<LabBuilder />} />
            <Route path="/campaign"    element={<LabNotebook />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const initSession = useMaestroStore((s) => s.initSession);
  useEffect(() => { initSession(); }, [initSession]);

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}