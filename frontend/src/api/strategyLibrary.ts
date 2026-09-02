import { apiClient } from "@/api/client";
import type { Strategy, StrategyTemplateDetail, StrategyTemplateSummary } from "@/types/api";

export interface CreateFromTemplatePayload {
  name?: string;
  preset?: string | null;
  parameters?: Record<string, unknown>;
}

export interface BacktestReportPayload {
  symbols: string[];
  timeframe?: string;
  start?: string;
  end?: string;
  preset?: string;
  capital?: number;
  parameters?: Record<string, unknown>;
}

export interface SymbolStat {
  symbol: string;
  trades: number;
  net_pnl: number;
  win_rate_pct: number;
  avg_trade: number;
  largest_winner: number;
  largest_loser: number;
}

export interface BacktestReport {
  slug: string;
  strategy_name: string;
  preset: string;
  timeframe: string;
  start: string;
  end: string;
  capital: number;
  requested_symbols: string[];
  used_symbols: string[];
  skipped: { symbol: string; reason: string }[];
  parameters: Record<string, unknown>;
  metrics: Record<string, number | null>;
  charts: {
    drawdown_curve?: [string, number][];
    monthly_returns?: Record<string, number>;
  };
  equity_curve: [string, number][];
  per_symbol: SymbolStat[];
  trades: Record<string, unknown>[];
  data_quality: { ok: boolean; warnings?: string[]; errors?: string[] };
  caveats: string[];
  generated_at: string;
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

  nifty200: () =>
    apiClient
      .get<{ universe: string; symbols: string[] }>("/strategy-library/universe/nifty200")
      .then((r) => r.data.symbols),

  backtestReport: (slug: string, payload: BacktestReportPayload) =>
    apiClient
      .post<BacktestReport>(`/strategy-library/${slug}/backtest-report`, payload)
      .then((r) => r.data),

  downloadBacktestReportPdf: async (slug: string, payload: BacktestReportPayload) => {
    const res = await apiClient.post(`/strategy-library/${slug}/backtest-report.pdf`, payload, {
      responseType: "blob",
    });
    const cd = String(res.headers["content-disposition"] ?? "");
    const m = /filename="?([^"]+)"?/.exec(cd);
    const name = m?.[1] ?? `${slug}-backtest-report.pdf`;
    const url = URL.createObjectURL(res.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
