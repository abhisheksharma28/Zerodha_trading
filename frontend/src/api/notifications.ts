import { apiClient } from "@/api/client";

export type IdeaGrade = "A" | "B" | "C";

export interface NotificationConfig {
  enabled: boolean;
  telegram_chat_id: string | null;
  notify_new_ideas: boolean;
  notify_idea_outcomes: boolean;
  notify_paper_fills: boolean;
  notify_daily_summary: boolean;
  idea_min_grade: IdeaGrade;
}

export interface NotificationStatus {
  config: NotificationConfig;
  token_present: boolean;
  connected: boolean;
  bot_username: string | null;
  bot_error: string | null;
}

export interface TelegramChat {
  chat_id: string;
  chat_title: string;
  chat_type: string;
  last_text: string;
}

export interface NotificationLogItem {
  id: string;
  created_at: string | null;
  sent_at: string | null;
  kind: string;
  title: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  last_error: string | null;
}

export interface TestResult {
  ok: boolean;
  status: string;
  error: string | null;
}

export const notificationsApi = {
  config: () =>
    apiClient.get<NotificationStatus>("/notifications/config").then((r) => r.data),
  setConfig: (patch: Partial<NotificationConfig>) =>
    apiClient.put<NotificationStatus>("/notifications/config", patch).then((r) => r.data),
  test: () => apiClient.post<TestResult>("/notifications/test").then((r) => r.data),
  detectChats: () =>
    apiClient
      .get<{ chats: TelegramChat[] }>("/notifications/telegram/updates")
      .then((r) => r.data.chats),
  log: (limit = 50) =>
    apiClient
      .get<{ items: NotificationLogItem[] }>("/notifications/log", { params: { limit } })
      .then((r) => r.data.items),
};
