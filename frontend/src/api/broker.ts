import { apiClient } from "@/api/client";
import type { BrokerStatus } from "@/types/api";

export const brokerApi = {
  status: () => apiClient.get<BrokerStatus>("/broker/status").then((r) => r.data),
  loginUrl: () => apiClient.get<{ login_url: string }>("/broker/login-url").then((r) => r.data),
  exchangeSession: (requestToken: string) =>
    apiClient
      .post<BrokerStatus>("/broker/session", { request_token: requestToken })
      .then((r) => r.data),
  disconnect: () => apiClient.post("/broker/disconnect"),
};
