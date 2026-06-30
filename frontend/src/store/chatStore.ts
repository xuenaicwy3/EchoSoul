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
  isStreaming: boolean;
  pendingInterrupt: { thread_id: string; sensitive_tools: { name: string }[]; message: string } | null;
  affection: AffectionResponse | null;

  addSession: (roleType: string) => string;
  removeSession: (id: string) => void;
  setActiveSession: (id: string) => void;
  activeSession: () => Session | undefined;

  addMessage: (msg: Message) => void;
  appendToLastAiMessage: (text: string) => string;  // 返回消息 id
  finalizeLastAiMessage: (emotion?: any) => void;
  setMessages: (msgs: Message[]) => void;
  setLoading: (v: boolean) => void;
  setStreaming: (v: boolean) => void;
  setPendingInterrupt: (data: { thread_id: string; sensitive_tools: { name: string }[]; message: string } | null) => void;
  setAffection: (aff: AffectionResponse) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  isLoading: false,
  isStreaming: false,
  pendingInterrupt: null,
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

  // SSE 流式：追加 token 到当前 AI 消息末尾
  appendToLastAiMessage: (text: string) => {
    const activeId = get().activeSessionId;
    if (!activeId) return "";
    let msgId = "";
    set((s) => ({
      sessions: s.sessions.map((sess) => {
        if (sess.id !== activeId) return sess;
        const msgs = [...sess.messages];
        const last = msgs[msgs.length - 1];
        if (last && last.sender === "ai" && last.isStreaming) {
          // 追加到现有流式消息
          last.text += text;
          msgId = last.id;
        } else {
          // 创建新的流式消息
          const newMsg: Message = {
            id: crypto.randomUUID(),
            sender: "ai",
            text: text,
            timestamp: new Date().toISOString(),
            isStreaming: true,
          };
          msgs.push(newMsg);
          msgId = newMsg.id;
        }
        return { ...sess, messages: msgs };
      }),
    }));
    return msgId;
  },

  // SSE 流式：标记 AI 消息完成
  finalizeLastAiMessage: (emotion?: any) => {
    const activeId = get().activeSessionId;
    if (!activeId) return;
    set((s) => ({
      sessions: s.sessions.map((sess) => {
        if (sess.id !== activeId) return sess;
        const msgs = [...sess.messages];
        const last = msgs[msgs.length - 1];
        if (last && last.sender === "ai") {
          last.isStreaming = false;
          if (emotion) last.emotion = emotion;
        }
        return { ...sess, messages: msgs };
      }),
    }));
  },

  setLoading: (v: boolean) => set({ isLoading: v }),

  setStreaming: (v: boolean) => set({ isStreaming: v }),

  setPendingInterrupt: (data) => set({ pendingInterrupt: data }),

  setAffection: (aff: AffectionResponse) => set({ affection: aff }),
}));
