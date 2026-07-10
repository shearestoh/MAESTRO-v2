import { AgentChat }          from "@/components/agent/AgentChat";
import { LiveWorkflowCanvas } from "@/components/workflow/LiveWorkflowCanvas";
import { ExecutionLog }       from "@/components/shared/ExecutionLog";
import { ResourceSchedule }   from "@/components/shared/ResourceSchedule";
import { Visualisation }      from "@/components/shared/Visualisation";
import { useMaestroStore }    from "@/store/maestroStore";

const panelHeaderCls = "text-sm font-semibold text-slate-700";

export function Dashboard() {
  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-50">
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_1fr_280px] gap-3 p-4 min-h-0">

        {/* Chat */}
        <div className="glass-panel flex flex-col overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-200 shrink-0">
            <h2 className="text-sm font-semibold text-slate-700">Chat with MAESTRO</h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <AgentChat />
          </div>
        </div>

        {/* Workflow Monitor + Execution Log */}
        <div className="flex flex-col gap-3 min-h-0">
          <div className="glass-panel flex flex-col flex-1 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-slate-200 shrink-0">
              <h2 className={panelHeaderCls}>Workflow monitor</h2>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <LiveWorkflowCanvas />
            </div>
          </div>
          <div className="h-44 shrink-0">
            <ExecutionLog />
          </div>
        </div>

        {/* Right panel */}
        <div className="flex flex-col gap-3 overflow-y-auto min-h-0">
          <Visualisation />
          <WorkflowStatus />
        </div>
      </div>

      {/* Task Schedule */}
      <div className="shrink-0 px-4 pb-4">
        <ResourceSchedule />
      </div>
    </div>
  );
}

function WorkflowStatus() {
  const items = useMaestroStore((s) => s.state?.timeline ?? []);

  const styles = {
    done:    "text-green-600",
    active:  "text-blue-600",
    pending: "text-slate-400",
  };
  const icons = { done: "●", active: "◉", pending: "○" };

  return (
    <div className="glass-panel p-4 space-y-2 flex-1">
      <div className={`${panelHeaderCls} mb-1`}>Workflow status</div>
      {items.length === 0 && (
        <div className="text-xs text-slate-400 italic">No active workflow.</div>
      )}
      {items.map((item, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 text-xs font-medium ${styles[item.status]}`}
        >
          <span className="shrink-0">{icons[item.status]}</span>
          <span className="leading-tight">{item.label}</span>
        </div>
      ))}
    </div>
  );
}