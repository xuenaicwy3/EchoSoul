import { useCallback } from "react";
import { sendMessage, getChatResult, getAffection, getChatHistory } from "../api/client";
import { useChatStore } from "../store/chatStore";
import { useRoleStore } from "../store/roleStore";
import type { Message } from "../types/chat";

export function useChat() {
  const { addMessage, setMessages, setLoading, setAffection } = useChatStore();
  const { selectedRole } = useRoleStore();

  const send = useCallback(
    async (text: string) => {
      if (!text.trim()) return;

      // Add user message
      const userMsg: Message = {
        id: crypto.randomUUID(),
        sender: "user",
        text: text.trim(),
        timestamp: new Date().toISOString(),
      };
      addMessage(userMsg);
      setLoading(true);

      try {
        // Send to backend
        const { task_id } = await sendMessage(text, selectedRole ?? undefined);

        // Poll for result
        let attempts = 0;
        while (attempts < 60) {
          await new Promise((r) => setTimeout(r, 1000));
          const result = await getChatResult(task_id);
          if (result.status === "pending") {
            attempts++;
            continue;
          }
          if (result.error) {
            addMessage({
              id: crypto.randomUUID(),
              sender: "ai",
              text: `错误: ${result.error}`,
              timestamp: new Date().toISOString(),
            });
            break;
          }
          // Success — 用 task_id 去重（防止 WS 重复推送）
          addMessage({
            id: task_id,
            sender: "ai",
            text: result.reply || "",
            timestamp: new Date().toISOString(),
            task_id: task_id,
            emotion: result.emotion,
          });
          break;
        }
      } catch (err) {
        addMessage({
          id: crypto.randomUUID(),
          sender: "ai",
          text: `发送失败: ${err instanceof Error ? err.message : "未知错误"}`,
          timestamp: new Date().toISOString(),
        });
      } finally {
        setLoading(false);
      }
    },
    [addMessage, setLoading, selectedRole],
  );

  const loadAffection = useCallback(async () => {
    if (!selectedRole) return;
    try {
      const aff = await getAffection(selectedRole);
      setAffection(aff);
    } catch {
      // silent
    }
  }, [selectedRole, setAffection]);

  const loadHistory = useCallback(async (roleType: string) => {
    try {
      const data = await getChatHistory(roleType); // 首页 50 条
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
  }, [setMessages]);

  const loadMoreHistory = useCallback(async (roleType: string, before: string) => {
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
  }, []);

  return { send, loadAffection, loadHistory, loadMoreHistory };
}
