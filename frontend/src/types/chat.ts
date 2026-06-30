export interface ChatRequest {
  message: string;
  role_type?: string;
}

export interface ChatResult {
  task_id?: string;
  reply?: string;
  emotion?: { label: string; score: number };
  role?: string;
  status?: string;
  error?: string;
}

export interface AffectionResponse {
  intimacy: number;
  trust: number;
  fun: number;
  growth: number;
  level: number;
  unlocks: string[];
}

export interface Message {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  task_id?: string;
  emotion?: { label: string; score: number };
  isStreaming?: boolean;  // SSE 流式中标记
}
