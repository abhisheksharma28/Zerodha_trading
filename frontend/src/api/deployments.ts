import { apiClient } from "@/api/client";
import type { Deployment, TradingMode } from "@/types/api";

export interface CreateDeploymentPayload {
  strategy_version_id: string;
  name: string;
  mode: TradingMode;
  instrument_universe: string[];
  config?: Record<string, unknown>;
  // Required, and must be exactly "DEPLOY LIVE TRADING", when mode === "live".
  // See backend/app/schemas/deployment.py DeploymentCreate.validate_live_confirmation
  // and backend/app/execution/guard.py for why this friction is deliberate.
  live_trading_confirmation_phrase?: string;
}

export const deploymentsApi = {
  list: () => apiClient.get<Deployment[]>("/deployments").then((r) => r.data),
  get: (id: string) => apiClient.get<Deployment>(`/deployments/${id}`).then((r) => r.data),
  create: (payload: CreateDeploymentPayload) =>
    apiClient.post<Deployment>("/deployments", payload).then((r) => r.data),
  deploy: (id: string) =>
    apiClient.post<Deployment>(`/deployments/${id}/deploy`).then((r) => r.data),
  pause: (id: string) =>
    apiClient.post<Deployment>(`/deployments/${id}/pause`).then((r) => r.data),
  resume: (id: string) =>
    apiClient.post<Deployment>(`/deployments/${id}/resume`).then((r) => r.data),
  stop: (id: string) =>
    apiClient.post<Deployment>(`/deployments/${id}/stop`).then((r) => r.data),
  clone: (id: string, payload: { name: string; mode: TradingMode; live_trading_confirmation_phrase?: string }) =>
    apiClient.post<Deployment>(`/deployments/${id}/clone`, payload).then((r) => r.data),
};
