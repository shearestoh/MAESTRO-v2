import { useMaestroStore } from "@/store/maestroStore";

export function Campaign() {
  const state    = useMaestroStore((s) => s.state);
  const campaign = state?.extracted_campaign;
  const results  = state?.results_store ?? [];

  return (
    <div className="flex flex-col h-full p-4 gap-4 overflow-y-auto">
      <div>
        <h1 className="text-lg font-bold text-slate-100">Campaign Designer</h1>
        <p className="text-xs text-slate-500">Active experimental campaign and results. Optimiser mode selection coming in Phase 3.</p>
      </div>

      {campaign ? (
        <div className="grid grid-cols-2 gap-4">
          <div className="glass-panel p-4 space-y-3">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Extracted Campaign</div>
            <div className="text-base font-bold text-slate-100">{campaign.title}</div>
            {[
              { label: "Case Study",  value: campaign.target_case_study },
              { label: "Objective",   value: campaign.objective_metric  },
              { label: "Status",      value: campaign.status            },
            ].map(({ label, value }) => (
              <div key={label} className="flex gap-2 text-xs">
                <span className="text-slate-500 w-24 shrink-0">{label}</span>
                <span className="text-slate-200 font-medium">{value}</span>
              </div>
            ))}
            <div className="border-t border-slate-700 pt-3 space-y-1">
              <div className="text-xs text-slate-500 font-semibold">Parameter Space</div>
              {campaign.parameter_space.map((p) => (
                <div key={p.name} className="flex justify-between text-xs">
                  <span className="text-slate-400">{p.name}</span>
                  <span className="font-mono text-blue-400">{p.min}–{p.max} {p.unit}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            {results.map((r) => (
              <div key={r.power_W} className="glass-panel p-3 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-bold text-slate-100">{r.power_W} W</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${r.X.length > 0 ? "bg-green-500/20 text-green-400" : "bg-slate-700 text-slate-500"}`}>
                    {r.X.length} evals
                  </span>
                </div>
                {r.best_energy !== null && (
                  <div className="text-xs text-slate-400">
                    Best: <span className="text-green-400 font-mono">{r.best_energy.toFixed(2)} Wh/kg</span>
                    {" "}@ AM={r.best_am?.toFixed(1)}%, Por={r.best_por?.toFixed(1)}%
                  </div>
                )}
                <div className="w-full h-1 bg-slate-700 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500" style={{ width: `${Math.min(100, (r.X.length / 20) * 100)}%` }} />
                </div>
              </div>
            ))}
            {results.length === 0 && (
              <div className="glass-panel p-6 text-center text-slate-500 text-sm italic">
                No results yet. Run a campaign to see results here.
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="glass-panel p-10 text-center space-y-2">
          <div className="text-4xl">📋</div>
          <div className="text-sm font-semibold text-slate-200">No campaign extracted yet</div>
          <div className="text-xs text-slate-500">Upload a paper in Reproducibility, or ask MAESTRO to design a campaign.</div>
        </div>
      )}
    </div>
  );
}