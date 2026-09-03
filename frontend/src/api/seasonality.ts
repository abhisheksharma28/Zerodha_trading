import { apiClient } from "@/api/client";

export interface SectorAudit {
  sector: string;
  ok: boolean;
  status: "PASS" | "WARN" | "FAIL";
  data_start: string | null;
  data_end: string | null;
  years_available: number;
  trading_days: number;
  complete_months: number;
  duplicate_dates: number;
  invalid_prices: number;
  non_monotonic_dates: number;
  max_gap_days: number;
  base_year: number | null;
  launch_year: number | null;
  pre_launch_years: number;
  issues: string[];
}

export interface MonthRankingRow {
  sector: string;
  rank: number;
  mean_edge_pct: number;
  median_edge_pct: number;
  win_rate: number;
  t_stat: number;
  q_value: number;
  n: number;
  long_score: number;
  short_score: number;
  confidence: number;
  stability: string | null;
  visual: string;
  bootstrap_prob_positive: number | null;
  bootstrap_prob_negative: number | null;
}

export interface MonthBlock {
  month: number;
  name: string;
  anchor: string | null;
  ranking: MonthRankingRow[];
  long_candidates: MonthRankingRow[];
  short_candidates: MonthRankingRow[];
}

export interface SeasonCell {
  sector: string;
  month: number;
  n: number;
  tier: string;
  mean_edge_pct: number;
  median_edge_pct: number;
  std_edge_pct: number;
  min_edge_pct: number;
  max_edge_pct: number;
  win_rate: number;
  loss_rate: number;
  mean_return_pct: number;
  t_stat: number;
  p_value: number;
  effect_size_d: number;
  ci95_edge_pct: [number, number] | null;
  t_label: string;
  q_value?: number;
  fdr_label?: string;
  visual?: string;
  long_score?: number;
  short_score?: number;
  confidence?: number;
  mean_market_adj_pct?: number;
  mean_cross_rank?: number;
  bootstrap?: {
    available: boolean;
    ci95?: [number, number];
    prob_positive?: number;
    prob_negative?: number;
    iterations?: number;
  };
  horizons?: {
    by_horizon: Record<string, { n: number; mean_edge_pct: number | null; win_rate?: number }>;
    stability_score: number | null;
    stability: string;
    trend?: string;
    direction_consistent: boolean | null;
  };
  regime?: {
    all: { n: number; mean_edge_pct: number | null };
    bull: { n: number; mean_edge_pct: number | null };
    bear: { n: number; mean_edge_pct: number | null };
    high_vol: { n: number; mean_edge_pct: number | null };
    low_vol: { n: number; mean_edge_pct: number | null };
    regime_dependency: number | null;
    regime_dependent: boolean;
  };
}

export interface WalkForwardResult {
  strategy: string;
  mode: string;
  start_test: string;
  end_test: string;
  n_months: number;
  long_cost_bps: number;
  short_cost_bps: number;
  equity_curve: [string, number][];
  metrics: Record<string, number | null>;
  rank_ic: {
    mean: number | null;
    median: number | null;
    pct_positive_months: number | null;
    n_months: number;
  };
  spread: {
    mean_pct: number | null;
    median_pct: number | null;
    pct_positive_months: number | null;
    n_months: number;
  };
  oos_split: {
    in_sample: Record<string, number | string | null>;
    out_of_sample: Record<string, number | string | null>;
  };
  trades: {
    date: string;
    side: string;
    sector: string;
    predicted_rank: number;
    gross_pct: number;
    net_pct: number;
  }[];
}

export interface SeasonalityReport {
  available: boolean;
  reason?: string;
  as_of?: string;
  built_at?: string;
  method?: string;
  verdict?: string;
  verdict_detail?: string;
  fdr_survivors?: {
    sector: string;
    month: number;
    month_name: string;
    mean_edge_pct: number;
    q_value: number;
    direction: string;
  }[];
  data_audit?: Record<string, SectorAudit>;
  index_timeline?: Record<string, { base_year: number; launch_year: number }>;
  sectors?: string[];
  sector_count?: number;
  history_span?: { earliest: string | null; latest: string | null };
  grid?: Record<string, Record<string, SeasonCell>>;
  months?: Record<string, MonthBlock>;
  current_month?: MonthBlock;
  fdr?: {
    n_tested: number;
    n_significant_q05: number;
    n_significant_q10: number;
    method: string;
  };
  regime_sample?: Record<string, { trend: string; vol: string }>;
  backtests?: {
    generated_at: string;
    strategies: Record<string, WalkForwardResult | { error: string }>;
  };
}

export interface SeasonalityStatus {
  state: "idle" | "running" | "done" | "stalled" | "error";
  note?: string;
  updated_at?: string;
  pid?: number;
}

export interface ModelVersion {
  id: string;
  version: string;
  name: string;
  status: "frozen" | "retired";
  frozen_at: string | null;
  methodology_hash: string;
  params: Record<string, unknown>;
  verdict: string | null;
  notes: string | null;
}

export interface SeasonalSignal {
  id: string;
  signal_ref: string;
  model_version_id: string;
  for_month: string;
  generated_at: string | null;
  data_cutoff: string;
  rankings: MonthRankingRow[];
  long_candidates: MonthRankingRow[];
  short_candidates: MonthRankingRow[];
  status: "generated" | "reviewed";
  review: {
    rank_ic: number | null;
    predicted_best: string | null;
    actual_best: string | null;
    predicted_worst: string | null;
    actual_worst: string | null;
    long_return_pct: number | null;
    short_return_pct: number | null;
    long_short_spread_pct: number | null;
  } | null;
  reviewed_at: string | null;
}

export const seasonalityApi = {
  report: () => apiClient.get<SeasonalityReport>("/seasonality").then((r) => r.data),
  status: () => apiClient.get<SeasonalityStatus>("/seasonality/status").then((r) => r.data),
  refresh: () =>
    apiClient.post<{ job?: string; pid?: number; error?: string }>("/seasonality/refresh").then((r) => r.data),
  backtest: (params: {
    strategy?: string;
    mode?: string;
    start_test_year?: number;
    long_cost_bps?: number;
    short_cost_bps?: number;
  }) => apiClient.get<WalkForwardResult>("/seasonality/backtest", { params }).then((r) => r.data),

  versions: () => apiClient.get<ModelVersion[]>("/seasonality/versions").then((r) => r.data),
  freeze: (body: { version: string; name: string; notes?: string }) =>
    apiClient.post<ModelVersion>("/seasonality/versions", body).then((r) => r.data),
  signals: (versionId?: string) =>
    apiClient
      .get<SeasonalSignal[]>("/seasonality/signals", { params: versionId ? { version_id: versionId } : {} })
      .then((r) => r.data),
  generateSignal: (versionId: string, forMonth?: string) =>
    apiClient
      .post<SeasonalSignal>(
        `/seasonality/versions/${versionId}/signal`,
        null,
        { params: forMonth ? { for_month: forMonth } : {} },
      )
      .then((r) => r.data),
  reviewSignal: (signalId: string) =>
    apiClient.post<SeasonalSignal>(`/seasonality/signals/${signalId}/review`).then((r) => r.data),
  health: (versionId: string) =>
    apiClient
      .get<Record<string, unknown>>(`/seasonality/versions/${versionId}/health`)
      .then((r) => r.data),
};

export const STRATEGY_LABELS: Record<string, string> = {
  A_long_best: "A · Long the single best sector",
  B_short_worst: "B · Short the single worst sector",
  C_long_top3: "C · Long the top 3 sectors",
  D_short_bottom3: "D · Short the bottom 3 sectors",
  E_long_top3_short_bottom3: "E · Long top 3 / short bottom 3",
  F_top20_bottom20: "F · Long top 20% / short bottom 20%",
};
