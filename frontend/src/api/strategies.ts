import { apiClient } from "@/api/client";
import type { Strategy, StrategyDetail, StrategyVersion } from "@/types/api";

export interface CreateStrategyPayload {
  name: string;
  description?: string;
  initial_version: {
    source_code: string;
    parameters?: Record<string, unknown>;
    entry_point?: string;
    change_summary?: string;
  };
}

export interface AddVersionPayload {
  source_code: string;
  parameters?: Record<string, unknown>;
  entry_point?: string;
  change_summary?: string;
}

export const strategiesApi = {
  list: () => apiClient.get<Strategy[]>("/strategies").then((r) => r.data),
  get: (id: string) => apiClient.get<StrategyDetail>(`/strategies/${id}`).then((r) => r.data),
  create: (payload: CreateStrategyPayload) =>
    apiClient.post<Strategy>("/strategies", payload).then((r) => r.data),
  addVersion: (strategyId: string, payload: AddVersionPayload) =>
    apiClient
      .post<StrategyVersion>(`/strategies/${strategyId}/versions`, payload)
      .then((r) => r.data),
  compareVersions: (a: string, b: string) =>
    apiClient
      .get(`/strategies/versions/compare`, { params: { a, b } })
      .then((r) => r.data),
};
