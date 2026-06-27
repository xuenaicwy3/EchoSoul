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
