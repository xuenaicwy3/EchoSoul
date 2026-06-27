import { create } from "zustand";
import type { Message, AffectionResponse } from "../types/chat";

export interface Session {
  id: string;
  roleType: string;
  label: string;
  messages: Message[];
}

interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;
  isLoading: boolean;
  affection: AffectionResponse | null;

  addSession: (roleType: string) => string;
  removeSession: (id: string) => void;
  setActiveSession: (id: string) => void;
  activeSession: () => Session | undefined;

  addMessage: (msg: Message) => void;
  setMessages: (msgs: Message[]) => void;
  setLoading: (v: boolean) => void;
  setAffection: (aff: AffectionResponse) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  isLoading: false,
  affection: null,

  addSession: (roleType: string) => {
    // 去重：已有同角色会话则直接切换
    const existing = get().sessions.find((s) => s.roleType === roleType);
    if (existing) {
      set({ activeSessionId: existing.id });
      return existing.id;
    }
    const id = crypto.randomUUID();
    const session: Session = { id, roleType, label: roleType, messages: [] };
    set((s) => ({
      sessions: [...s.sessions, session],
      activeSessionId: id,
    }));
    return id;
  },

  removeSession: (id: string) => {
    set((s) => {
      const sessions = s.sessions.filter((sess) => sess.id !== id);
      const activeSessionId =
        s.activeSessionId === id
          ? (sessions.length > 0 ? sessions[sessions.length - 1].id : null)
          : s.activeSessionId;
      return { sessions, activeSessionId };
    });
  },

  setActiveSession: (id: string) => set({ activeSessionId: id }),

  activeSession: () => {
    const { sessions, activeSessionId } = get();
    return sessions.find((s) => s.id === activeSessionId);
  },

  addMessage: (msg: Message) => {
    const activeId = get().activeSessionId;
    if (!activeId) return;
    set((s) => {
      const activeSess = s.sessions.find((sess) => sess.id === activeId);
      if (!activeSess) return s;
      // 去重：如果 task_id 已存在，跳过
      if (msg.task_id && activeSess.messages.some((m) => m.task_id === msg.task_id)) {
        return s;
      }
      return {
        sessions: s.sessions.map((sess) =>
          sess.id === activeId
            ? { ...sess, messages: [...sess.messages, msg] }
            : sess,
        ),
      };
    });
  },

  setMessages: (msgs: Message[]) => {
    const activeId = get().activeSessionId;
    if (!activeId) return;
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === activeId ? { ...sess, messages: msgs } : sess,
      ),
    }));
  },

  setLoading: (v: boolean) => set({ isLoading: v }),

  setAffection: (aff: AffectionResponse) => set({ affection: aff }),
}));
