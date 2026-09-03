import { apiClient } from "@/api/client";

export interface AssistantStatus {
  available: boolean;
  model: string | null;
  reason: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  model: string;
  grounding: { symbols: string[]; sectors: string[]; had_data: boolean };
}

export const assistantApi = {
  status: () => apiClient.get<AssistantStatus>("/assistant/status").then((r) => r.data),
  suggestions: () =>
    apiClient.get<{ suggestions: string[] }>("/assistant/suggestions").then((r) => r.data.suggestions),
  chat: (messages: ChatMessage[]) =>
    apiClient.post<ChatResponse>("/assistant/chat", { messages }).then((r) => r.data),
};
