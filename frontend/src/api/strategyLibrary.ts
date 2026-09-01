import { apiClient } from "@/api/client";
import type { Strategy, StrategyTemplateDetail, StrategyTemplateSummary } from "@/types/api";

export interface CreateFromTemplatePayload {
  name?: string;
  preset?: string | null;
  parameters?: Record<string, unknown>;
}

export const strategyLibraryApi = {
  list: () =>
    apiClient.get<StrategyTemplateSummary[]>("/strategy-library").then((r) => r.data),
  get: (slug: string) =>
    apiClient.get<StrategyTemplateDetail>(`/strategy-library/${slug}`).then((r) => r.data),
  createFromTemplate: (slug: string, payload: CreateFromTemplatePayload) =>
    apiClient
      .post<Strategy>(`/strategy-library/${slug}/strategies`, payload)
      .then((r) => r.data),
  seed: () =>
    apiClient
      .post<{ created: string[]; skipped: string[] }>("/strategy-library/seed")
      .then((r) => r.data),
};
