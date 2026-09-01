import { apiClient } from "@/api/client";
import type { OrderRow } from "@/types/api";

export const ordersApi = {
  byDeployment: (deploymentId: string) =>
    apiClient.get<OrderRow[]>(`/orders/by-deployment/${deploymentId}`).then((r) => r.data),
  byBacktest: (backtestId: string) =>
    apiClient.get<OrderRow[]>(`/orders/by-backtest/${backtestId}`).then((r) => r.data),
};
