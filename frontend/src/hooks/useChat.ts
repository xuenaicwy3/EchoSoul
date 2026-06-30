import { useCallback, useRef } from "react";
import { streamChat, getAffection, getChatHistory } from "../api/client";
import { useChatStore } from "../store/chatStore";
import { useRoleStore } from "../store/roleStore";
import type { Message } from "../types/chat";

export function useChat() {
  const {
    addMessage,
    appendToLastAiMessage,
    finalizeLastAiMessage,
    setMessages,
    setLoading,
    setStreaming,
    setPendingInterrupt,
    setAffection,
  } = useChatStore();
  const { selectedRole } = useRoleStore();
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (text: string) => {
      if (!text.trim()) return;

      // 添加用户消息
      const userMsg: Message = {
        id: crypto.randomUUID(),
        sender: "user",
        text: text.trim(),
        timestamp: new Date().toISOString(),
      };
      addMessage(userMsg);
      setLoading(true);
      setStreaming(true);

      // SSE 流式对话
      abortRef.current = streamChat(
        text.trim(),
        selectedRole ?? undefined,
        {
          onToken: (token: string) => {
            appendToLastAiMessage(token);
          },
          onInterrupt: (data) => {
            finalizeLastAiMessage();
            setPendingInterrupt({
              thread_id: data.thread_id,
              sensitive_tools: (data as any).sensitive_tools || [],
              message: data.message,
            });
            setLoading(false);
            setStreaming(false);
          },
          onFinal: (data) => {
            finalizeLastAiMessage(data.emotion);
            setLoading(false);
            setStreaming(false);
          },
          onError: (message: string) => {
            addMessage({
              id: crypto.randomUUID(),
              sender: "ai",
              text: `发送失败: ${message}`,
              timestamp: new Date().toISOString(),
            });
            setLoading(false);
            setStreaming(false);
          },
        },
      );
    },
    [addMessage, appendToLastAiMessage, finalizeLastAiMessage, setLoading, setStreaming, selectedRole],
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setLoading(false);
    setStreaming(false);
  }, [setLoading, setStreaming]);

  const loadAffection = useCallback(async () => {
    if (!selectedRole) return;
    try {
      const aff = await getAffection(selectedRole);
      setAffection(aff);
    } catch {
      // silent
    }
  }, [selectedRole, setAffection]);

  const loadHistory = useCallback(
    async (roleType: string) => {
      try {
        const data = await getChatHistory(roleType);
        const history = data.history || [];
        const msgs: Message[] = history
          .map((h: { sender: string; message: string; timestamp: string }) => ({
            id: crypto.randomUUID(),
            sender: h.sender as "user" | "ai",
            text: h.message,
            timestamp: h.timestamp,
          }))
          .reverse();
        if (msgs.length > 0) setMessages(msgs);
      } catch {
        // silent
      }
    },
    [setMessages],
  );

  const loadMoreHistory = useCallback(
    async (roleType: string, before: string) => {
      try {
        const data = await getChatHistory(roleType, before);
        const history = data.history || [];
        const older: Message[] = history
          .map((h: { sender: string; message: string; timestamp: string }) => ({
            id: crypto.randomUUID(),
            sender: h.sender as "user" | "ai",
            text: h.message,
            timestamp: h.timestamp,
          }))
          .reverse();
        return older;
      } catch {
        return [];
      }
    },
    [],
  );

  const resumeInterrupt = useCallback(
    async (approved: string[], rejected: string[]) => {
      const interrupt = useChatStore.getState().pendingInterrupt;
      if (!interrupt) return;
      setPendingInterrupt(null);
      setStreaming(true);

      try {
        const token = localStorage.getItem("echosoul_token");
        const res = await fetch("/chat/resume", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ thread_id: interrupt.thread_id, approved, rejected }),
        });
        if (!res.ok) { setStreaming(false); return; }
        const reader = res.body?.getReader();
        if (!reader) { setStreaming(false); return; }
        const decoder = new TextDecoder();
        let buffer = "";
        const read = () => {
          reader.read().then(({ done, value }) => {
            if (done) { setStreaming(false); return; }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            let eventType = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) eventType = line.slice(7).trim();
              else if (line.startsWith("data: ") && eventType === "token") {
                try { appendToLastAiMessage(JSON.parse(line.slice(6)).content || ""); } catch {}
              }
            }
            read();
          });
        };
        read();
      } catch { setStreaming(false); }
    },
    [setPendingInterrupt, setStreaming, appendToLastAiMessage],
  );

  return { send, stopStreaming, resumeInterrupt, loadAffection, loadHistory, loadMoreHistory };
}
