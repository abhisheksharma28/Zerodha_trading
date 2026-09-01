import { apiClient } from "@/api/client";
import type { OptionsEvaluation, OptionsInstance, OptionsTemplate } from "@/types/api";

export const optionsStrategiesApi = {
  template: () =>
    apiClient.get<OptionsTemplate>("/options-strategies/template").then((r) => r.data),
  list: () =>
    apiClient.get<OptionsInstance[]>("/options-strategies").then((r) => r.data),
  create: (body: { mode?: string; preset?: string; parameters?: Record<string, unknown> }) =>
    apiClient.post<OptionsInstance>("/options-strategies", body).then((r) => r.data),
  get: (id: string) =>
    apiClient.get<OptionsInstance>(`/options-strategies/${id}`).then((r) => r.data),
  evaluate: (id: string) =>
    apiClient.post<OptionsEvaluation>(`/options-strategies/${id}/evaluate`).then((r) => r.data),
  enter: (id: string) =>
    apiClient.post<OptionsInstance>(`/options-strategies/${id}/enter`).then((r) => r.data),
  exit: (id: string) =>
    apiClient.post<OptionsInstance>(`/options-strategies/${id}/exit`).then((r) => r.data),
};
