import { apiClient } from "@/api/client";
import type { Backtest } from "@/types/api";

export interface CreateBacktestPayload {
  strategy_version_id: string;
  instrument_universe: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  timeframe?: string;
}

export const backtestsApi = {
  list: () => apiClient.get<Backtest[]>("/backtests").then((r) => r.data),
  get: (id: string) => apiClient.get<Backtest>(`/backtests/${id}`).then((r) => r.data),
  create: (payload: CreateBacktestPayload) =>
    apiClient.post<Backtest>("/backtests", payload).then((r) => r.data),
};
