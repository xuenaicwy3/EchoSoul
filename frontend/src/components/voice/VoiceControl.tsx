import { useState, useCallback } from "react";
import { useVoiceChat } from "../../hooks/useVoiceChat";

export default function VoiceControl() {
  const { isListening, isSpeaking, asrText, startListening, stopListening } = useVoiceChat();
  const [error, setError] = useState("");

  const handleToggle = useCallback(async () => {
    setError("");
    try {
      if (isListening) {
        stopListening();
      } else {
        await startListening();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "麦克风不可用");
    }
  }, [isListening, startListening, stopListening]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px" }}>
      <button
        onClick={handleToggle}
        title={isListening ? "停止语音" : "开始语音"}
        style={{
          width: 44,
          height: 44,
          borderRadius: "50%",
          border: "none",
          cursor: "pointer",
          fontSize: 20,
          background: isListening
            ? "#ef4444"
            : isSpeaking
              ? "#8b5cf6"
              : "#e5989b",
          color: "#fff",
          boxShadow: isListening ? "0 0 12px rgba(239,68,68,0.5)" : "none",
          transition: "all 0.2s",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {isListening ? "⏹" : isSpeaking ? "🔊" : "🎤"}
      </button>
      {asrText && (
        <span style={{ fontSize: 12, color: "#888", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {asrText}
        </span>
      )}
      {error && (
        <span style={{ fontSize: 12, color: "#ef4444" }}>{error}</span>
      )}
    </div>
  );
}
