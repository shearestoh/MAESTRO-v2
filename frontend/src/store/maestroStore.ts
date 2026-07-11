import { create } from "zustand";
import type {
  SessionState, WsEvent, WorkflowPlan,
  LabSettings, OptimisationLibraryEntry, VirtualInstrument,
} from "@/types";
import { api } from "@/lib/api";

interface MaestroStore {
  sessionId:            string | null;
  state:                SessionState | null;
  isLoading:            boolean;
  error:                string | null;
  wsConnected:          boolean;
  liveEvents:           WsEvent[];
  lastEvent:            WsEvent | null;
  sidebarOpen:          boolean;
  labSettings:          LabSettings | null;
  optimisationLibrary:  OptimisationLibraryEntry[];
  instruments:          VirtualInstrument[];
  optimisticMessage:    string | null;

  initSession:             () => Promise<void>;
  refreshState:            () => Promise<void>;
  sendMessage:             (text: string) => Promise<void>;
  confirm:                 (proceed: boolean) => Promise<void>;
  executePlan:             (plan: WorkflowPlan) => Promise<void>;
  reset:                   () => Promise<void>;
  pushWsEvent:             (event: WsEvent) => void;
  setWsConnected:          (v: boolean) => void;
  setSidebarOpen:          (v: boolean) => void;
  clearError:              () => void;
  loadLabSettings:         () => Promise<void>;
  saveLabSettings:         (updates: Partial<LabSettings>) => Promise<void>;
  loadOptimisationLibrary: () => Promise<void>;
  updateOptimiser:         (name: string, nCalls: number, nInitPts: number) => Promise<void>;
  loadInstruments:         () => Promise<void>;
}

export const useMaestroStore = create<MaestroStore>((set, get) => ({
  sessionId:           null,
  state:               null,
  isLoading:           false,
  error:               null,
  wsConnected:         false,
  liveEvents:          [],
  lastEvent:           null,
  sidebarOpen:         true,
  labSettings:         null,
  optimisationLibrary: [],
  instruments:         [],
  optimisticMessage:   null,

  initSession: async () => {
    set({ isLoading: true, error: null });
    try {
      const stored    = localStorage.getItem("maestro_session_id");
      let   sessionId = stored;

      if (sessionId) {
        try {
          const res = await api.getState(sessionId);
          set({ sessionId, state: res.state, isLoading: false });
          return;
        } catch {
          localStorage.removeItem("maestro_session_id");
          sessionId = null;
        }
      }

      const created  = await api.createSession();
      sessionId      = created.session_id;
      localStorage.setItem("maestro_session_id", sessionId);
      const stateRes = await api.getState(sessionId);
      set({ sessionId, state: stateRes.state, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  refreshState: async () => {
    const { sessionId, optimisticMessage } = get();
    if (!sessionId) return;
    try {
      const res    = await api.getState(sessionId);
      const isDone = !res.state.background_job_active ||
        res.state.background_job_status === "completed" ||
        res.state.background_job_status === "failed";

      // Clear optimistic message once the backend has echoed it back
      const echoed = optimisticMessage && res.state.messages.some(
        (m) => m.role === "user" && m.content === optimisticMessage
      );

      set((s) => ({
        state:             res.state,
        isLoading:         isDone ? false : s.isLoading,
        optimisticMessage: echoed ? null : s.optimisticMessage,
      }));
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  sendMessage: async (text) => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ isLoading: true, optimisticMessage: text });
    try {
      const res = await api.sendMessage(sessionId, text);
      set({ state: res.state, isLoading: false, optimisticMessage: null });
    } catch (e) {
      set({ error: String(e), isLoading: false, optimisticMessage: null });
    }
  },

  confirm: async (proceed) => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ isLoading: true });
    try {
      const res = await api.confirm(sessionId, proceed);
      set({ state: res.state, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  executePlan: async (plan) => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ isLoading: true });
    try {
      const res = await api.executePlan(sessionId, plan);
      set({ state: res.state, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  reset: async () => {
    const { sessionId } = get();
    if (sessionId) {
      try {
        await api.reset(sessionId);
      } catch {
        // Session may no longer exist on backend; continue with local reset
      }
    }
    localStorage.removeItem("maestro_session_id");
    const created  = await api.createSession();
    localStorage.setItem("maestro_session_id", created.session_id);
    const stateRes = await api.getState(created.session_id);
    set({
      sessionId:         created.session_id,
      state:             stateRes.state,
      liveEvents:        [],
      lastEvent:         null,
      isLoading:         false,
      error:             null,
      optimisticMessage: null,
    });
  },

  pushWsEvent: (event) =>
    set((s) => ({
      liveEvents: [...s.liveEvents.slice(-49), event],
      lastEvent:  event,
    })),

  setWsConnected: (v) => set({ wsConnected: v }),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  clearError:     ()  => set({ error: null }),

  loadLabSettings: async () => {
    try {
      const res = await api.getLabSettings();
      set({ labSettings: res.settings });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  saveLabSettings: async (updates) => {
    try {
      const res = await api.updateLabSettings(updates);
      set({ labSettings: res.settings });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  loadOptimisationLibrary: async () => {
    try {
      const res = await api.listOptimisationLibrary();
      set({ optimisationLibrary: res.libraries });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  updateOptimiser: async (name, nCalls, nInitPts) => {
    const { sessionId } = get();
    if (!sessionId) return;
    try {
      const res = await api.updateSessionOptimiser(sessionId, name, nCalls, nInitPts);
      set({ state: res.state });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  loadInstruments: async () => {
    try {
      const res = await api.listTools();
      set({ instruments: res.tools });
    } catch (e) {
      set({ error: String(e) });
    }
  },
}));