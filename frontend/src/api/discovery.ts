import { apiClient } from "@/api/client";

export interface DiscoveryUnivInstrument {
  symbol: string;
  name: string;
  asset_class: string;
  sub_class: string;
  region: string;
  currency: string;
  ingested: boolean;
  tier: string | null;
  quality_score: number | null;
  data_start: string | null;
  data_end: string | null;
  n_points: number;
  bar_interval: string | null;
}

export interface DiscoveryUniverse {
  n_defined: number;
  n_ingested: number;
  by_tier: Record<string, number>;
  by_asset_class: Record<string, number>;
  tier_a_common_start: string | null;
  fx: Record<string, number>;
  last_ingest: {
    at: string | null;
    source: string | null;
    bar_interval: string | null;
    n_instruments: number;
    n_bars: number;
  };
  instruments: DiscoveryUnivInstrument[];
}

export interface ScreenRow {
  symbol: string;
  screen_score: number;
  cluster: number | null;
  metrics: Record<string, number | null>;
  category_ranks: Record<string, number>;
}

export interface DiscoveryScreen {
  currency: string;
  n: number;
  period_start: string | null;
  period_end: string | null;
  weights: Record<string, number>;
  instruments: ScreenRow[];
  excluded: string[];
}

export interface PortfolioMetrics {
  cagr_pct?: number;
  ann_vol_pct?: number;
  sharpe?: number;
  sortino?: number;
  max_drawdown_pct?: number;
  ulcer_index?: number;
  positive_period_pct?: number;
  effective_n?: number;
  annual_turnover_pct?: number;
  corr_to_market?: number | null;
  [k: string]: number | null | undefined;
}

export interface RegimeBucket {
  n: number;
  return_pct: number;
  ann_vol_pct: number | null;
}

export interface SearchValidation {
  verdict: "pass" | "downgrade" | "reject";
  stability_score: number;
  label: string;
  rejections: string[];
  deflated_sharpe: number | null;
  psr: number | null;
  block_bootstrap: {
    available: boolean;
    cagr_pct?: Record<string, number>;
    max_drawdown_pct?: Record<string, number>;
    sharpe?: Record<string, number>;
    prob_negative_cagr?: number;
    prob_dd_worse_than_25pct?: number;
  };
  perturbation: {
    available: boolean;
    base_alpha_score?: number;
    perturbed_mean?: number;
    worst?: number;
    max_drop?: number;
    fragile?: boolean;
  };
  start_date_sensitivity: {
    available: boolean;
    windows?: number;
    sharpe_median?: number;
    sharpe_worst?: number;
    cagr_median_pct?: number;
    cagr_worst_pct?: number;
  };
  stability_components: Record<string, number>;
}

export interface SearchTopRow {
  rank: number;
  weights: Record<string, number>;
  alpha_score: number;
  on_pareto_frontier: boolean;
  metrics: PortfolioMetrics;
  category_scores: Record<string, number>;
  out_of_sample: Record<string, number>;
  by_regime: Record<string, RegimeBucket>;
  validation?: SearchValidation;
  final_score?: number;
}

export interface ParetoRow {
  weights: Record<string, number>;
  alpha_score: number;
  cagr_pct?: number;
  sharpe?: number;
  max_drawdown_pct?: number;
}

export interface SearchResult {
  available: boolean;
  reason?: string;
  method: string;
  seed: number;
  tested: number;
  kept: number;
  elapsed_s: number;
  top: SearchTopRow[];
  survivors: SearchTopRow[];
  pareto_frontier: ParetoRow[];
  run_id?: string | null;
}

export interface ValidateResult {
  available: boolean;
  reason?: string;
  evaluation?: Record<string, unknown>;
  validation?: SearchValidation & {
    alpha_score: number;
    components: Record<string, number>;
    deflated_sharpe: Record<string, number | boolean>;
    verdict: "pass" | "downgrade" | "reject";
  };
}

export interface SearchRunRow {
  id: string;
  started_at: string;
  method: string;
  currency: string;
  seed: number;
  n_tested: number;
  n_kept: number;
  n_survivors: number;
  universe: string[];
  params: Record<string, unknown>;
  top_alpha: number | null;
  best_survivor: SearchTopRow | null;
}

export interface SearchParams {
  method?: "monte_carlo" | "genetic";
  n_min?: number;
  n_max?: number;
  n_portfolios?: number;
  wmax?: number;
  currency?: string;
  seed?: number;
  validate_top?: number;
  symbols?: string[];
}

export const discoveryApi = {
  universe: () =>
    apiClient.get<DiscoveryUniverse>("/discovery/universe").then((r) => r.data),

  screen: (currency = "USD") =>
    apiClient
      .get<DiscoveryScreen>("/discovery/screen", { params: { currency } })
      .then((r) => r.data),

  candidates: (k = 16, currency = "USD") =>
    apiClient
      .get<{ n_clusters: number; candidates: string[]; clusters: Record<string, string[]> }>(
        "/discovery/candidates",
        { params: { k, currency } },
      )
      .then((r) => r.data),

  search: ({ symbols, ...q }: SearchParams) =>
    apiClient
      .post<SearchResult>(
        "/discovery/search",
        symbols && symbols.length ? { symbols } : {},
        { params: q },
      )
      .then((r) => r.data),

  validate: (weights: Record<string, number>, n_trials = 1, currency = "USD") =>
    apiClient
      .post<ValidateResult>(
        "/discovery/validate",
        { weights },
        { params: { n_trials, currency } },
      )
      .then((r) => r.data),

  runs: (limit = 20) =>
    apiClient
      .get<{ runs: SearchRunRow[] }>("/discovery/runs", { params: { limit } })
      .then((r) => r.data.runs),
};
