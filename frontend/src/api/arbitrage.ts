import { apiClient } from "@/api/client";

export type ArbCategory =
  | "TRUE_ARBITRAGE"
  | "STATISTICAL_ARBITRAGE"
  | "RELATIVE_VALUE"
  | "BASIS_ARBITRAGE"
  | "LATENCY_DEPENDENT"
  | "RESEARCH_ONLY";

export interface ArbStrategyDetail {
  slug: string;
  name: string;
  category: ArbCategory;
  description: string;
  logic: string;
  legs: string;
  data_requirements: string[];
  latency_sensitivity: string;
  min_net_edge_bps_default: number;
  infra_note: string;
  warning: string;
  supported_timeframes: string[];
  parameters: Record<string, { type: string; default: unknown; description: string; min?: number; max?: number; choices?: unknown[]; group?: string }>;
  presets: Record<string, Record<string, unknown>>;
  n_legs: number;
}

export interface ArbLibrary {
  strategies: ArbStrategyDetail[];
  categories: Record<string, string>;
  net_edge_rule: string;
  roadmap: { implemented: string[]; planned: string[] };
}

export interface ArbTradeLeg {
  instrument: string;
  side: string;
  target_qty: number;
  filled_qty: number;
  entry_price: number;
  exit_price: number;
  entry_cost: number;
  exit_cost: number;
}
export interface ArbTrade {
  strategy: string;
  direction: string;
  legs: ArbTradeLeg[];
  entry_ts: string;
  exit_ts: string;
  bars_held: number;
  gross_pnl: number;
  total_costs: number;
  financing_cost: number;
  net_pnl: number;
  entry_net_edge: number;
  realized_edge: number;
  edge_capture_rate: number;
  leg_imbalance: number;
  partial_fill: boolean;
  converged: boolean;
  exit_reason: string;
}

export interface ArbBacktest {
  slug: string;
  strategy_name: string;
  category: ArbCategory;
  legs: string[];
  preset: string;
  timeframe: string;
  start: string;
  end: string;
  sync_mode: string;
  params: Record<string, unknown>;
  metrics: Record<string, number | null>;
  data_quality: Record<string, number | string>;
  diagnostics: { rejected?: Record<string, number> };
  opportunities_seen: number;
  opportunities_executed: number;
  equity_curve: [string, number][];
  trades: ArbTrade[];
  warning: string;
  infra_note: string;
  generated_at: string;
}

export interface ArbPair {
  symbol_a: string;
  symbol_b: string;
  hedge_ratio: number;
  return_correlation: number;
  adf_tstat: number | null;
  cointegrated: boolean;
  half_life_bars: number | null;
  spread_stability: number;
  liquidity_score: number;
  same_sector: string | boolean | null;
  tradeable: boolean;
  discovery_score: number;
  bars_used: number;
}

export interface ArbDiscovery {
  available?: boolean;
  universe_size: number;
  requested: number;
  skipped: { symbol: string; reason: string }[];
  timeframe: string;
  days: number;
  adf_threshold: number;
  pairs: ArbPair[];
  tradeable_count: number;
  generated_at: string;
}

export interface ArbPortfolio {
  runs: {
    slug: string;
    strategy_name: string;
    category: ArbCategory;
    legs: string[];
    preset: string;
    opportunities: number;
    executed: number;
    net_pnl: number | null;
    return_on_capital_pct: number | null;
    sharpe_ratio: number | null;
    max_drawdown_pct: number | null;
    avg_net_edge: number | null;
    edge_capture_rate: number | null;
    convergence_rate: number | null;
    arbitrage_quality_score: number | null;
    data_quality_score: number | null;
    generated_at: string;
  }[];
  run_count: number;
  combined_net_pnl: number;
  note: string;
}

interface BacktestBody {
  slug: string;
  symbol_a: string;
  symbol_b: string;
  timeframe?: string;
  start?: string;
  end?: string;
  preset?: string;
  parameters?: Record<string, unknown>;
  sync_mode?: string;
}

export const arbitrageApi = {
  library: () => apiClient.get<ArbLibrary>("/arbitrage/strategies").then((r) => r.data),
  strategy: (slug: string) =>
    apiClient.get<ArbStrategyDetail>(`/arbitrage/strategies/${slug}`).then((r) => r.data),
  runBacktest: (body: BacktestBody) =>
    apiClient.post<ArbBacktest>("/arbitrage/backtest", body).then((r) => r.data),
  listBacktests: () =>
    apiClient
      .get<{ runs: { slug: string; strategy_name: string; legs: string[]; preset: string; timeframe: string; metrics: Record<string, number | null>; generated_at: string }[] }>(
        "/arbitrage/backtests",
      )
      .then((r) => r.data.runs),
  pairDiscovery: (body: { symbols: string[]; timeframe?: string; days?: number; adf_threshold?: number; top_n?: number }) =>
    apiClient.post<ArbDiscovery>("/arbitrage/pair-discovery", body).then((r) => r.data),
  latestDiscovery: () =>
    apiClient.get<ArbDiscovery>("/arbitrage/pair-discovery/latest").then((r) => r.data),
  portfolio: () => apiClient.get<ArbPortfolio>("/arbitrage/portfolio").then((r) => r.data),
  scanner: () =>
    apiClient
      .get<{ available: boolean; reason?: string; opportunities: unknown[]; statuses: string[] }>(
        "/arbitrage/scanner",
      )
      .then((r) => r.data),
};
