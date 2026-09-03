import { apiClient } from "@/api/client";

export interface CanonicalConfig {
  slug: string;
  universe_name: string;
  universe_size: number;
  timeframe: string;
  preset: string;
  years: number;
  capital: number;
  max_gross_exposure: number;
  config_hash: string;
  note: string;
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

export interface BacktestBlock {
  metrics: Record<string, number | null>;
  ruined: boolean;
  generated_at: string | null;
  stale_config: boolean;
  top_symbols: SymbolStat[];
}

export interface LiveBlock {
  available: boolean;
  deployments: number;
  since: string | null;
  days_live: number;
  fills: number;
  note?: string;
  realised_pnl?: number;
  closed_trades?: number;
  win_rate_pct?: number;
  avg_trade?: number;
  sharpe_daily_ann?: number;
}

export interface Percentiles {
  p5?: number;
  p25?: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface RobustnessBlock {
  slug: string;
  generated_at?: string;
  robustness_score: number;
  notes: string[];
  full_window_metrics?: Record<string, number | null>;
  monte_carlo: {
    available: boolean;
    reason?: string;
    n_trades?: number;
    n_sims?: number;
    actual_return_pct?: number;
    actual_max_dd_pct?: number;
    bootstrap?: {
      return_pct: Percentiles;
      max_dd_pct: { p50: number; p75: number; p95: number };
      prob_loss: number;
      prob_ruin: number;
      prob_dd_beyond_threshold: number;
    };
    reshuffle?: { max_dd_pct: { p50: number; p95: number }; prob_ruin: number };
    dd_threshold_pct?: number;
  };
  walk_forward: {
    available: boolean;
    folds?: {
      fold: number;
      is_start: string;
      oos_start: string;
      oos_end: string;
      is_metrics?: Record<string, number | null>;
      oos_metrics?: Record<string, number | null>;
      error?: string;
    }[];
    is_sharpe_mean?: number;
    oos_sharpe_mean?: number;
    sharpe_decay?: number;
    oos_profitable_folds?: number;
    total_folds?: number;
    walk_forward_efficiency?: number | null;
  };
  sensitivity: {
    available: boolean;
    reason?: string;
    param?: string;
    preset_value?: number;
    preset_rank?: number;
    best_value?: number;
    best_sharpe?: number;
    overfit_risk?: boolean;
    surface?: { value: number; sharpe: number; return_pct: number; max_dd_pct: number }[];
  };
}

export type TuningVerdict =
  | "recommend_tuned"
  | "keep_preset"
  | "no_eligible_combo";

export interface TuningSurfaceRow {
  params: Record<string, unknown>;
  is_preset: boolean;
  is_sharpe: number;
  oos_sharpe: number;
  is_return_pct: number;
  oos_return_pct: number;
  oos_trades: number;
  total_trades: number | null;
  ruined: boolean;
  robust_score: number | null;
}

export interface TuningSummary {
  verdict: TuningVerdict;
  recommended_overrides: Record<string, unknown> | null;
  currently_adopted: Record<string, unknown> | null;
  generated_at?: string;
  explanation?: string;
}

export interface TuningDetail extends TuningSummary {
  slug: string;
  config: CanonicalConfig;
  in_sample_frac: number;
  min_sharpe_edge: number;
  preset_params: Record<string, unknown>;
  preset_row: TuningSurfaceRow | null;
  surface: TuningSurfaceRow[];
  ranked_top: TuningSurfaceRow[];
}

export interface KpiSummary {
  min: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  max: number;
  mean: number;
  std: number;
}

export interface ParamSimBlock {
  pct: number;
  n_samples: number;
  seed?: number;
  perturbed_params: string[];
  base: Record<string, number>;
  base_ruined?: boolean;
  ruined_fraction: number;
  distribution: Record<string, KpiSummary>;
  verdict: "stable" | "fragile";
  notes: string[];
  generated_at?: string;
}

export interface ParamSimSummary {
  pct: number;
  n_samples: number;
  verdict: "stable" | "fragile";
  ruined_fraction: number;
  sharpe: Partial<KpiSummary>;
  return_pct: Partial<KpiSummary>;
  generated_at?: string;
}

export interface LeaderboardRow {
  slug: string;
  name: string;
  category: string;
  rank: number | null;
  composite_score: number | null;
  canonical: CanonicalConfig | null;
  unsuited_reason: string | null;
  backtest: BacktestBlock | null;
  live: LiveBlock | null;
  robustness: RobustnessBlock | null;
  tuning: TuningSummary | null;
  param_sim: ParamSimSummary | null;
}

export interface Leaderboard {
  generated_at: string;
  score_method: string;
  rows: LeaderboardRow[];
  any_backtest_cached: boolean;
}

export interface LeaderboardDetail {
  slug: string;
  config: CanonicalConfig;
  generated_at: string;
  used_symbols: string[];
  skipped: { symbol: string; reason: string }[];
  metrics: Record<string, number | null>;
  ruined: boolean;
  peak_gross_exposure_pct: number | null;
  equity_curve: [string, number][];
  top_symbols: SymbolStat[];
  bottom_symbols: SymbolStat[];
  caveats: string[];
  live: LiveBlock | null;
  robustness: RobustnessBlock | null;
  tuning: TuningDetail | null;
  param_sim: ParamSimBlock | null;
}

export interface CatalogSummary {
  verdict: "strong" | "tradeable" | "marginal" | "avoid" | "ruined" | "insufficient";
  headline: string;
  what_we_did: string[];
  what_we_saw: string[];
  what_to_look_at: string[];
}

export interface CatalogEntry {
  slug: string;
  name: string;
  category: string;
  universe: string;
  timeframe: string;
  years: number;
  screen?: string;
  design_note?: string;
  stale: boolean;
  status: "ok" | "ruined" | "not_run";
  metrics: Record<string, number | null> | null;
  summary: CatalogSummary | null;
  equity_curve: [string, number][];
  top_symbols?: { symbol: string; net_pnl: number }[];
  cached_at: number | null;
  used_symbols?: number;
  skipped?: number;
  universe_rationale?: string | null;
  screen_metrics?: Record<string, number | string> | null;
}

export interface BacktestCatalog {
  meta: {
    catalog_size: number;
    catalog_ran: number;
    user_backtests: number;
    total_backtests: number;
    last_refresh: number | null;
    universe: string | null;
  };
  strategies: CatalogEntry[];
}

export interface RefreshStatus {
  state: "idle" | "running" | "done" | "error" | "stalled";
  pid?: number;
  started_at?: string;
  updated_at?: string;
  total?: number | null;
  completed?: number;
  current?: string | null;
  results?: Record<string, string>;
  elapsed_s?: number;
  error?: string;
  note?: string;
}

export interface RefreshJob {
  job: string;
  pid: number;
  slugs: string[] | "all";
  status_url: string;
}

export const leaderboardApi = {
  get: () => apiClient.get<Leaderboard>("/leaderboard").then((r) => r.data),

  catalog: () => apiClient.get<BacktestCatalog>("/leaderboard/catalog").then((r) => r.data),

  detail: (slug: string) =>
    apiClient.get<LeaderboardDetail>(`/leaderboard/${slug}`).then((r) => r.data),

  refresh: (slugs?: string[]) =>
    apiClient
      .post<RefreshJob>("/leaderboard/refresh", { slugs })
      .then((r) => r.data),

  refreshOne: (slug: string) =>
    apiClient.post<RefreshJob>(`/leaderboard/refresh/${slug}`).then((r) => r.data),

  refreshStatus: () =>
    apiClient.get<RefreshStatus>("/leaderboard/refresh/status").then((r) => r.data),

  runRobustness: (slug: string) =>
    apiClient.post<RobustnessBlock>(`/leaderboard/robustness/${slug}`).then((r) => r.data),

  runTuning: (slug: string) =>
    apiClient.post<TuningDetail>(`/leaderboard/tune/${slug}`).then((r) => r.data),

  runParamSim: (slug: string, pct = 5, n = 30) =>
    apiClient
      .post<ParamSimBlock>(`/leaderboard/param-sim/${slug}`, null, {
        params: { pct, n_samples: n },
      })
      .then((r) => r.data),

  adoptTuned: (slug: string, overrides: Record<string, unknown> | null) =>
    apiClient
      .post<{ slug: string; adopted: Record<string, unknown> }>(
        `/leaderboard/tune/${slug}/adopt`,
        { overrides },
      )
      .then((r) => r.data),

  createPaperDeployments: () =>
    apiClient
      .post<{ results: Record<string, string> }>("/leaderboard/paper-deployments")
      .then((r) => r.data.results),
};
