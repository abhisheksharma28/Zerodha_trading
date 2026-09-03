import { apiClient } from "@/api/client";

export interface EditorStarter {
  source: string;
  entry_point: string;
  api: {
    base_class: string;
    must_define: string;
    on_bar: string;
    helpers: string[];
    indicators: string;
    allowed_imports: string;
    limits: string;
  };
}

export interface ValidateResult {
  ok: boolean;
  error?: string;
  stage?: string;
  name?: string;
  slug?: string;
  category?: string;
  supported_timeframes?: string[];
  min_instruments?: number;
  max_instruments?: number | null;
  params?: Record<string, { type: string; default: unknown; description: string; group?: string }>;
  presets?: string[];
}

export interface EditorBacktestResult {
  ok: boolean;
  error?: string;
  stage?: string;
  name?: string;
  timeframe?: string;
  start?: string;
  end?: string;
  capital?: number;
  used_symbols?: string[];
  skipped?: { symbol: string; reason: string }[];
  parameters?: Record<string, unknown>;
  metrics?: Record<string, number | null>;
  equity_curve?: [string, number][];
  per_symbol?: { symbol: string; trades: number; net_pnl: number; win_rate_pct: number }[];
  trades?: Record<string, unknown>[];
  caveats?: string[];
  generated_at?: string;
}

export interface EditorBacktestBody {
  source: string;
  entry_point?: string;
  symbols: string[];
  timeframe: string;
  start?: string;
  end?: string;
  preset?: string;
  capital?: number;
  overrides?: Record<string, unknown>;
}

export const strategyEditorApi = {
  starter: () => apiClient.get<EditorStarter>("/strategy-editor/starter").then((r) => r.data),
  validate: (source: string, entry_point = "Strategy") =>
    apiClient
      .post<ValidateResult>("/strategy-editor/validate", { source, entry_point })
      .then((r) => r.data),
  backtest: (body: EditorBacktestBody) =>
    apiClient.post<EditorBacktestResult>("/strategy-editor/backtest", body).then((r) => r.data),
  save: (body: { source: string; entry_point?: string; name?: string; description?: string }) =>
    apiClient
      .post<{ ok: boolean; strategy_id: string; name: string }>("/strategy-editor/save", body)
      .then((r) => r.data),
};
