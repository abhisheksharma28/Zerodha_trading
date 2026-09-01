import { apiClient } from "@/api/client";
import type { Backtest, BacktestReport } from "@/types/api";

export interface CreateBacktestPayload {
  strategy_version_id: string;
  instrument_universe: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  timeframe?: string;
}

export interface RunBacktestPayload {
  candles?: Record<string, Array<[string, number, number, number, number, number]>>;
  costs?: Record<string, number>;
}

export const backtestsApi = {
  list: () => apiClient.get<Backtest[]>("/backtests").then((r) => r.data),
  get: (id: string) => apiClient.get<Backtest>(`/backtests/${id}`).then((r) => r.data),
  create: (payload: CreateBacktestPayload) =>
    apiClient.post<Backtest>("/backtests", payload).then((r) => r.data),
  run: (id: string, payload: RunBacktestPayload = {}) =>
    apiClient.post<Backtest>(`/backtests/${id}/run`, payload).then((r) => r.data),
  report: (id: string) =>
    apiClient.get<BacktestReport>(`/backtests/${id}/report`).then((r) => r.data),
};
