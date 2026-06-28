import type { SessionState, VirtualInstrument, WorkflowPlan } from "@/types";

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

export const api = {
  // ── Session ────────────────────────────────────────────────────────────────
  createSession: () =>
    request<{ session_id: string }>("/session", { method: "POST", body: "{}" }),

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

  nextDay: (sessionId: string) =>
    request<{ state: SessionState }>("/next-day", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId }),
    }),

  reset: (sessionId: string) =>
    request<{ state: SessionState }>("/reset", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId }),
    }),

  // ── Phase 3: Execute plan ──────────────────────────────────────────────────
  executePlan: (sessionId: string, plan: WorkflowPlan) =>
    request<{ state: SessionState }>("/execute-plan", {
      method: "POST",
      body:   JSON.stringify({ session_id: sessionId, plan }),
    }),

  // ── Documents ──────────────────────────────────────────────────────────────
  uploadDocument: async (sessionId: string, file: File) => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const res = await fetch(`${BASE}/documents/upload`, {
      method: "POST",
      body:   form,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },

  getDocumentStructure: (documentId: string) =>
    request<{
      status:   string;
      title:    string;
      sections: unknown[];
      figures:  unknown[];
      tables:   unknown[];
    }>(`/documents/${documentId}/structure`),

  extractCaseStudy: async (
    sessionId:  string,
    documentId: string,
    caseName:   string,
  ) => {
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

  // ── Instrument registry ────────────────────────────────────────────────────
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

  // ── Plot ───────────────────────────────────────────────────────────────────
  getPlotUrl: (sessionId: string) => `${BASE}/plot/${sessionId}`,

  // ── Exports ────────────────────────────────────────────────────────────────
  exportResultsCsv:   (sessionId: string) =>
    fetch(`${BASE}/export/results-csv/${sessionId}`,   { method: "POST" }),
  exportResultsJson:  (sessionId: string) =>
    fetch(`${BASE}/export/results-json/${sessionId}`,  { method: "POST" }),
  exportCampaignJson: (sessionId: string) =>
    fetch(`${BASE}/export/campaign-json/${sessionId}`, { method: "POST" }),
};