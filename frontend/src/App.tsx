import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect }       from "react";
import { Sidebar }         from "@/components/layout/Sidebar";
import { Dashboard }       from "@/pages/Dashboard";
import { LabSetup }        from "@/pages/LabSetup";
import { LabNotebook }     from "@/pages/LabNotebook";
import { Campaign }        from "@/pages/Campaign";
import { useMaestroStore } from "@/store/maestroStore";
import { useWebSocket }    from "@/hooks/useWebSocket";
import { usePolling }      from "@/hooks/usePolling";

function AppShell() {
  useWebSocket();
  usePolling();

  const isBooting = useMaestroStore((s) => s.isLoading && !s.state);
  const error     = useMaestroStore((s) => s.error);
  const clearErr  = useMaestroStore((s) => s.clearError);

  if (isBooting) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-blue-600 flex items-center justify-center">
            <span className="text-white font-black text-xl">M</span>
          </div>
          <div className="text-sm text-slate-500">Connecting to MAESTRO...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {error && (
          <div className="bg-red-50 border-b border-red-200 px-4 py-2 flex items-center justify-between shrink-0">
            <span className="text-xs text-red-600">{error}</span>
            <button onClick={clearErr} className="text-xs text-red-500 hover:underline ml-4">
              Dismiss
            </button>
          </div>
        )}
        <main className="flex-1 min-h-0 overflow-hidden">
          <Routes>
            <Route path="/"         index element={<Dashboard />} />
            <Route path="/lab"      element={<LabSetup />} />
            <Route path="/notebook" element={<LabNotebook />} />
            <Route path="/campaign" element={<Campaign />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const initSession     = useMaestroStore((s) => s.initSession);
  const loadLabSettings = useMaestroStore((s) => s.loadLabSettings);

  useEffect(() => {
    initSession();
    loadLabSettings();
  }, [initSession, loadLabSettings]);

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}