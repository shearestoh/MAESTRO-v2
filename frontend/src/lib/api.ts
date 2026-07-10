import type {
  SessionState,
  VirtualInstrument,
  WorkflowPlan,
  LabSettings,
  DocumentLibraryEntry,
  OptimisationLibraryEntry,
  LabResource,
  ProtocolEntry,
} from "@/types";

const BASE = "/api";

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

async function downloadFile(response: Response, filename: string): Promise<void> {
  const blob = await response.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const api = {
  createSession: () =>
    request<{ session_id: string }>("/session", { method: "POST" }),

  getState: (sessionId: string) =>
    request<{ state: SessionState }>(`/state/${sessionId}`),

  sendMessage: (sessionId: string, text: string) =>
    request<{ state: SessionState }>("/message", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId, text }),
    }),

  confirm: (sessionId: string, proceed: boolean) =>
    request<{ state: SessionState }>("/confirm", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId, proceed }),
    }),

  reset: (sessionId: string) =>
    request<{ state: SessionState }>("/reset", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId }),
    }),

  executePlan: (sessionId: string, plan: WorkflowPlan) =>
    request<{ state: SessionState }>("/execute-plan", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId, plan }),
    }),

  uploadDocument: async (sessionId: string, file: File, docType: "paper" | "manual" = "paper") => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("doc_type",   docType);
    form.append("file",       file);
    const res = await fetch(`${BASE}/documents/upload`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },

  getDocumentStructure: (documentId: string) =>
    request<{
      status:   string;
      title:    string;
      authors:  string[];
      year:     number | null;
      doi:      string | null;
      journal:  string | null;
      sections: unknown[];
      figures:  unknown[];
      tables:   unknown[];
    }>(`/documents/${documentId}/structure`),

  extractCaseStudy: async (sessionId: string, documentId: string, caseName: string) => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("case_name",  caseName);
    const res = await fetch(
      `${BASE}/documents/${documentId}/extract-case-study`,
      { method: "POST", body: form },
    );
    if (!res.ok) throw new Error(`Extraction failed: ${res.status}`);
    return res.json();
  },

  listTools: () =>
    request<{ status: string; tools: VirtualInstrument[] }>("/tools"),

  registerTool: (toolData: Partial<VirtualInstrument>) =>
    request<{ status: string; tool: VirtualInstrument }>("/tools", {
      method: "POST",
      body:   JSON.stringify(toolData),
    }),

  updateTool: (toolId: string, updates: Partial<VirtualInstrument>) =>
    request<{ status: string; tool: VirtualInstrument }>(`/tools/${toolId}`, {
      method: "PUT",
      body:   JSON.stringify(updates),
    }),

  deleteTool: (toolId: string) =>
    request<{ status: string }>(`/tools/${toolId}`, { method: "DELETE" }),

  buildPlotUrl: (sessionId: string) => `${BASE}/plot/${sessionId}`,

  exportResultsCsv: async (sessionId: string) => {
    const res = await fetch(`${BASE}/export/results-csv/${sessionId}`, { method: "POST" });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    await downloadFile(res, "maestro_results.csv");
  },

  exportResultsJson: async (sessionId: string) => {
    const res = await fetch(`${BASE}/export/results-json/${sessionId}`, { method: "POST" });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    await downloadFile(res, "maestro_results.json");
  },

  exportCampaignJson: async (sessionId: string) => {
    const res = await fetch(`${BASE}/export/campaign-json/${sessionId}`, { method: "POST" });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    await downloadFile(res, "maestro_campaign.json");
  },

  getLabSettings: () =>
    request<{ status: string; settings: LabSettings }>("/lab-settings"),

  updateLabSettings: (updates: Partial<LabSettings>) =>
    request<{ status: string; settings: LabSettings }>("/lab-settings", {
      method: "PUT",
      body:   JSON.stringify(updates),
    }),

  listLibrary: () =>
    request<{ status: string; documents: DocumentLibraryEntry[] }>("/library"),

  removeFromLibrary: (documentId: string) =>
    request<{ status: string }>(`/library/${documentId}`, { method: "DELETE" }),

  listOptimisationLibrary: () =>
    request<{ status: string; libraries: OptimisationLibraryEntry[] }>("/optimisation-library"),

  addToOptimisationLibrary: (entry: Partial<OptimisationLibraryEntry>) =>
    request<{ status: string; entry: OptimisationLibraryEntry }>("/optimisation-library", {
      method: "POST",
      body:   JSON.stringify(entry),
    }),

  removeFromOptimisationLibrary: (libId: string) =>
    request<{ status: string }>(`/optimisation-library/${libId}`, { method: "DELETE" }),

  updateSessionOptimiser: (
    sessionId:      string,
    name:           string,
    nCalls:         number,
    nInitialPoints: number,
  ) =>
    request<{ state: SessionState }>("/optimiser", {
      method: "POST",
      body:   JSON.stringify({
        session_id:       sessionId,
        name,
        n_calls:          nCalls,
        n_initial_points: nInitialPoints,
      }),
    }),

  listResources: () =>
    request<{ status: string; resources: LabResource[] }>("/resources"),

  addResource: (data: Partial<LabResource>) =>
    request<{ status: string; resource: LabResource }>("/resources", {
      method: "POST",
      body:   JSON.stringify(data),
    }),

  updateResource: (resourceId: string, updates: Partial<LabResource>) =>
    request<{ status: string; resource: LabResource }>(`/resources/${resourceId}`, {
      method: "PUT",
      body:   JSON.stringify(updates),
    }),

  deleteResource: (resourceId: string) =>
    request<{ status: string }>(`/resources/${resourceId}`, { method: "DELETE" }),

  listProtocols: () =>
    request<{ status: string; protocols: ProtocolEntry[] }>("/protocols"),

  saveProtocol: (data: Partial<ProtocolEntry>) =>
    request<{ status: string; protocol: ProtocolEntry }>("/protocols", {
      method: "POST",
      body:   JSON.stringify(data),
    }),

  updateProtocol: (protocolId: string, updates: Partial<ProtocolEntry>) =>
    request<{ status: string; protocol: ProtocolEntry }>(`/protocols/${protocolId}`, {
      method: "PUT",
      body:   JSON.stringify(updates),
    }),

  deleteProtocol: (protocolId: string) =>
    request<{ status: string }>(`/protocols/${protocolId}`, { method: "DELETE" }),
};