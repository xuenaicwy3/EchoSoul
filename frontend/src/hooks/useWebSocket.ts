import { useEffect, useRef, useCallback } from "react";
import { useAuthStore } from "../store/authStore";

const WS_BASE = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}`;

type MessageHandler = (data: Record<string, unknown>) => void;

export function useWebSocket(onMessage: MessageHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const token = useAuthStore((s) => s.token);
  const userId = useAuthStore((s) => s.userId);

  const connect = useCallback(() => {
    if (!token || !userId) return;

    const ws = new WebSocket(`${WS_BASE}/ws/${userId}?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[WS] Connected");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data === "pong") return;
        onMessage(data as Record<string, unknown>);
      } catch {
        // non-JSON message, ignore
      }
    };

    ws.onclose = () => {
      console.log("[WS] Disconnected, reconnecting in 3s...");
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [token, userId, onMessage]);

  useEffect(() => {
    connect();

    // Heartbeat
    const heartbeat = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 30000);

    return () => {
      clearInterval(heartbeat);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { send };
}
