import axios from "axios";

// React 与 FastAPI 同源部署，使用相对路径
const client = axios.create({
  baseURL: "",
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// Request interceptor — attach JWT token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem("echosoul_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — handle 401
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("echosoul_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  },
);

// ---- Auth API ----

export async function login(username: string, password: string) {
  const res = await client.post("/auth/login", { username, password });
  return res.data;
}

export async function register(username: string, password: string) {
  const res = await client.post("/auth/register", { username, password });
  return res.data;
}

// ---- Chat API ----

export async function sendMessage(message: string, roleType?: string) {
  const res = await client.post("/chat", { message, role_type: roleType });
  return res.data;
}

export async function getChatResult(taskId: string) {
  const res = await client.get(`/chat/result/${taskId}`);
  return res.data;
}

// ---- SSE 流式对话 ----

export interface StreamCallbacks {
  onToken: (token: string) => void;
  onInterrupt?: (data: { message: string; thread_id: string; sensitive_tools?: { name: string }[] }) => void;
  onFinal: (data: { reply: string; emotion: any; role?: string; tools?: any[] }) => void;
  onError: (message: string) => void;
}

export function streamChat(
  message: string,
  roleType: string | undefined,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();
  const token = localStorage.getItem("echosoul_token");

  console.log("[SSE] streaming start...");
  fetch("/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, role_type: roleType }),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      callbacks.onError(`HTTP ${response.status}`);
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) {
      callbacks.onError("Response body is not readable");
      return;
    }
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events: "event: xxx\ndata: {...}\n\n"
      const lines = buffer.split("\n");
      buffer = lines.pop() || ""; // keep incomplete line in buffer

      let currentEvent = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const dataStr = line.slice(6);
          try {
            const data = JSON.parse(dataStr);
            if (currentEvent === "token") {
              callbacks.onToken(data.content || "");
            } else if (currentEvent === "interrupt") {
              callbacks.onInterrupt?.(data);
              controller.abort();  // 中断后停止读取
              return;
            } else if (currentEvent === "final") {
              callbacks.onFinal(data);
              return;  // 完成后停止读取
            } else if (currentEvent === "error") {
              callbacks.onError(data.message || "Unknown error");
              return;
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
    }
  }).catch((err) => {
    if (err.name !== "AbortError") {
      callbacks.onError(err.message);
    }
  });

  return controller;
}

export async function getAffection(roleType: string) {
  const res = await client.get(`/affection/${roleType}`);
  return res.data;
}

export async function getChatHistory(roleType: string, before?: string) {
  const params = before ? { before } : {};
  const res = await client.get(`/chat_history/${roleType}`, { params });
  return res.data;
}

export async function deleteChatHistory(roleType: string) {
  const res = await client.delete(`/chat_history/${roleType}`);
  return res.data;
}

export default client;
