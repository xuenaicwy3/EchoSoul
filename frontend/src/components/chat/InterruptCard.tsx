import { useChatStore } from "../../store/chatStore";
import { useChat } from "../../hooks/useChat";

export default function InterruptCard() {
  const { pendingInterrupt, isStreaming } = useChatStore();
  const { resumeInterrupt } = useChat();

  if (!pendingInterrupt) return null;

  const tools = pendingInterrupt.sensitive_tools || [];
  const allNames = tools.map((t) => t.name);

  const handleApprove = () => resumeInterrupt(allNames, []);
  const handleReject = () => resumeInterrupt([], allNames);

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      background: "rgba(0,0,0,0.5)", display: "flex",
      justifyContent: "center", alignItems: "center", zIndex: 9999,
    }}>
      <div style={{
        background: "#fff", borderRadius: 16, padding: 24,
        maxWidth: 360, width: "90%", boxShadow: "0 4px 24px rgba(0,0,0,0.2)",
      }}>
        <h3 style={{ margin: "0 0 8px" }}>⚠️ 操作审批</h3>
        <p style={{ color: "#666", fontSize: 14, marginBottom: 12 }}>
          AI 想执行以下操作：
        </p>
        <div style={{ marginBottom: 16 }}>
          {tools.map((t, i) => (
            <div key={i} style={{
              background: "#fff3e0", padding: "8px 12px",
              borderRadius: 8, marginBottom: 6, fontSize: 13,
            }}>
              🔧 {t.name}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={handleApprove} disabled={isStreaming} style={{
            flex: 1, padding: 10, border: "none", borderRadius: 8,
            background: "#4caf50", color: "#fff", fontSize: 15, cursor: "pointer",
          }}>
            ✅ 允许
          </button>
          <button onClick={handleReject} disabled={isStreaming} style={{
            flex: 1, padding: 10, border: "none", borderRadius: 8,
            background: "#f44336", color: "#fff", fontSize: 15, cursor: "pointer",
          }}>
            ❌ 拒绝
          </button>
        </div>
      </div>
    </div>
  );
}
