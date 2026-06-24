import { create } from "zustand";
import type { SessionState, WsEvent } from "@/types";
import { api } from "@/lib/api";

interface MaestroStore {
  // Session
  sessionId:   string | null;
  state:       SessionState | null;
  isLoading:   boolean;
  error:       string | null;

  // WebSocket
  wsConnected: boolean;
  liveEvents:  WsEvent[];
  lastEvent:   WsEvent | null;

  // UI
  sidebarOpen: boolean;

  // Actions
  initSession:    () => Promise<void>;
  refreshState:   () => Promise<void>;
  sendMessage:    (text: string) => Promise<void>;
  confirm:        (proceed: boolean) => Promise<void>;
  nextDay:        () => Promise<void>;
  reset:          () => Promise<void>;
  pushWsEvent:    (event: WsEvent) => void;
  setWsConnected: (v: boolean) => void;
  setSidebarOpen: (v: boolean) => void;
  clearError:     () => void;
}

export const useMaestroStore = create<MaestroStore>((set, get) => ({
  sessionId:   null,
  state:       null,
  isLoading:   false,
  error:       null,
  wsConnected: false,
  liveEvents:  [],
  lastEvent:   null,
  sidebarOpen: true,

  initSession: async () => {
    set({ isLoading: true, error: null });
    try {
      // Reuse stored session if available
      const stored    = sessionStorage.getItem("maestro_session_id");
      let   sessionId = stored;

      if (sessionId) {
        // Validate it still exists on the backend
        try {
          const res = await api.getState(sessionId);
          set({ sessionId, state: res.state, isLoading: false });
          return;
        } catch {
          // Session expired — create a new one
          sessionStorage.removeItem("maestro_session_id");
          sessionId = null;
        }
      }

      const created  = await api.createSession();
      sessionId      = created.session_id;
      sessionStorage.setItem("maestro_session_id", sessionId);
      const stateRes = await api.getState(sessionId);
      set({ sessionId, state: stateRes.state, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  refreshState: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    try {
      const res = await api.getState(sessionId);
      set({ state: res.state });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  sendMessage: async (text: string) => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ isLoading: true });
    try {
      const res = await api.sendMessage(sessionId, text);
      set({ state: res.state, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  confirm: async (proceed: boolean) => {
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

  nextDay: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    const res = await api.nextDay(sessionId);
    set({ state: res.state });
  },

  reset: async () => {
    sessionStorage.removeItem("maestro_session_id");
    const created  = await api.createSession();
    sessionStorage.setItem("maestro_session_id", created.session_id);
    const stateRes = await api.getState(created.session_id);
    set({
      sessionId:  created.session_id,
      state:      stateRes.state,
      liveEvents: [],
      lastEvent:  null,
    });
  },

  pushWsEvent: (event: WsEvent) =>
    set((s) => ({
      liveEvents: [...s.liveEvents.slice(-49), event],
      lastEvent:  event,
    })),

  setWsConnected: (v) => set({ wsConnected: v }),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  clearError:     ()  => set({ error: null }),
}));