import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import ChatWindow from "../components/chat/ChatWindow";
import ChatInput from "../components/chat/ChatInput";
import { useChat } from "../hooks/useChat";
import { useWebSocket } from "../hooks/useWebSocket";
import { useChatStore } from "../store/chatStore";
import { useRoleStore } from "../store/roleStore";
import { deleteChatHistory } from "../api/client";
import Live2DCanvas from "../components/live2d/Live2DCanvas";
import VRMCharacter from "../components/vrm/VRMCharacter";
import VoiceControl from "../components/voice/VoiceControl";
import { GLB_MODELS } from "../types/vrm";
import type { Message } from "../types/chat";

const ROLES = [
  "日系动漫型", "高冷御姐型", "傲娇辣妹型",
  "甜美校花型", "软萌可爱型", "温柔贤淑型",
  "元气少女型", "清冷仙气型",
];

export default function ChatPage() {
  const navigate = useNavigate();
  const { send, loadAffection, loadHistory } = useChat();
  const {
    sessions, activeSessionId,
    isLoading, addMessage, addSession, removeSession, setActiveSession, activeSession,
  } = useChatStore();
  const { selectedRole, setRole } = useRoleStore();

  // 首次进入没有会话时自动创建一个
  useEffect(() => {
    if (sessions.length === 0 && selectedRole && activeSessionId === null) {
      addSession(selectedRole);
    }
  }, []); // 仅 mount 时执行一次

  useWebSocket((data) => {
    if (data.type === "chat_reply") {
      const tid = (data.task_id as string) || "";
      addMessage({
        id: tid || crypto.randomUUID(), sender: "ai",
        text: (data.reply as string) || "",
        timestamp: new Date().toISOString(),
        task_id: tid || undefined,
        emotion: data.emotion as Message["emotion"],
      });
    }
  });

  useEffect(() => { loadAffection(); }, [loadAffection]);

  // 切换会话时从后端拉取历史记录
  useEffect(() => {
    const s = activeSession();
    if (s && s.messages.length === 0) {
      loadHistory(s.roleType);
    }
  }, [activeSessionId, activeSession, loadHistory]);

  if (!selectedRole) { navigate("/home", { replace: true }); return null; }

  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setDropdownOpen(false);
    };
    if (dropdownOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [dropdownOpen]);

  const handleAddSession = () => {
    if (selectedRole) addSession(selectedRole);
  };

  const currentSession = activeSession();
  const currentMessages = currentSession?.messages ?? [];

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <button className="back-btn" onClick={() => navigate("/home")}>← 返回</button>
          <h2>{currentSession?.roleType ?? selectedRole}</h2>
        </div>

        <div className="role-select-area">
          <div className="custom-select-wrapper" ref={dropdownRef}>
            <div className={`custom-select ${dropdownOpen ? "open" : ""}`} onClick={() => setDropdownOpen(!dropdownOpen)}>
              <span>{selectedRole}</span>
              <span className="arrow">▾</span>
            </div>
            <div className={`custom-options ${dropdownOpen ? "show" : ""}`}>
              {ROLES.map((r) => (
                <div
                  key={r}
                  className="custom-option"
                  onClick={() => { setRole(r); setDropdownOpen(false); }}
                >
                  {r}
                </div>
              ))}
            </div>
          </div>
          <button onClick={handleAddSession}>+</button>
        </div>

        <div className="session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeSessionId ? "active" : ""}`}
              onClick={() => setActiveSession(s.id)}
            >
              <div className="session-avatar">{s.label.charAt(0)}</div>
              <div className="session-info">
                <div className="session-name">{s.label}</div>
              </div>
              <button
                className="delete-session"
                onClick={(e) => { e.stopPropagation(); deleteChatHistory(s.roleType); removeSession(s.id); }}
                title="删除会话"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-nav">
          <button onClick={() => navigate("/game")}>游戏</button>
          <button onClick={() => navigate("/story")}>故事工坊</button>
          <button onClick={() => navigate("/memory")}>记忆</button>
        </div>
      </div>

      {/* Main Chat */}
      <div className="chat-main">
        {sessions.length === 0 ? (
          <div className="chat-empty" style={{ flex: 1 }}>
            <div>💬 点击上方 + 创建会话开始聊天</div>
          </div>
        ) : (
          <>
            <ChatWindow messages={currentMessages} isLoading={isLoading} />
            <div style={{ display: "flex", alignItems: "center", borderTop: "1px solid #f0d5d5" }}>
              <VoiceControl />
              <div style={{ flex: 1 }}>
                <ChatInput onSend={send} disabled={isLoading || !activeSessionId} />
              </div>
            </div>
          </>
        )}
      </div>

      {/* Live2D / VRM 双引擎悬浮窗 */}
      {(GLB_MODELS[currentSession?.roleType ?? selectedRole ?? ""] ? (
        <VRMCharacter roleType={currentSession?.roleType ?? selectedRole} />
      ) : (
        <Live2DCanvas
          roleType={currentSession?.roleType ?? selectedRole}
          onModelReady={(model: any) => {
            (window as any).__live2dModel = model;
          }}
        />
      ))}
    </div>
  );
}
