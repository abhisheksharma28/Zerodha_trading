import { apiClient } from "@/api/client";

export type Verdict = "BUY" | "HOLD" | "AVOID";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export interface ScreenerScores {
  value: number | null;
  quality: number | null;
  growth: number | null;
  technical: number | null;
}

export type TechnicalVerdict = "STRONG_BUY" | "BUY" | "NEUTRAL" | "SELL" | "STRONG_SELL";

export interface ScreenerRating {
  symbol: string;
  name: string | null;
  sector: string | null;
  verdict: Verdict;
  confidence: Confidence;
  composite: number;
  scores: ScreenerScores;
  data_completeness: number;
  ltp: number | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
  ta_verdict: TechnicalVerdict | null;
  ta_score: number | null;
  notes: string | null;
  as_of: string | null;
}

export interface TaGauge {
  label: string;
  buy: number;
  neutral: number;
  sell: number;
  verdict: TechnicalVerdict;
}

export interface TechnicalRatingRow extends ScreenerRating {
  ta_detail: {
    verdict: TechnicalVerdict;
    score: number;
    gauges: { moving_average: TaGauge; technical_indicators: TaGauge; overall: TaGauge };
    signals: Record<string, number>;
    readings: Record<string, number | null>;
  };
}

export interface TechnicalRatingsResponse {
  available: boolean;
  reason?: string;
  as_of?: string | null;
  summary: {
    strong_buy: number;
    buy: number;
    neutral: number;
    sell: number;
    strong_sell: number;
    total: number;
  };
  sectors?: string[];
  last_run: ScreenerRun | null;
  ratings: TechnicalRatingRow[];
}

export interface ScreenerRun {
  started_at: string | null;
  finished_at: string | null;
  trigger: string;
  universe_size: number;
  scored: number;
  buy: number;
  hold: number;
  avoid: number;
  error: string | null;
}

export interface ScreenerRatingsResponse {
  available: boolean;
  reason?: string;
  as_of?: string | null;
  summary: { buy: number; hold: number; avoid: number; total: number };
  sectors?: string[];
  last_run: ScreenerRun | null;
  ratings: ScreenerRating[];
}

export interface FactorRow {
  metric: string;
  raw: number | null;
  score: number | null;
}

export interface ScreenerRatingDetail extends ScreenerRating {
  available: boolean;
  reason?: string;
  metrics: Record<string, number | null>;
  factors: {
    peer_basis: "sector" | "universe";
    peer_count: number;
    weights: Record<string, number>;
    value: FactorRow[];
    quality: FactorRow[];
    growth: FactorRow[];
    technical: FactorRow[];
  };
}

export const DEEP_DIVE_SECTIONS = [
  ["business_model", "Business model"],
  ["quarterly_results", "Latest quarterly results"],
  ["balance_sheet", "Balance sheet health"],
  ["competitive_position", "Competitive position"],
  ["management_quality", "Management quality"],
  ["technical_setup", "Technical setup"],
  ["catalysts", "Key upcoming catalysts"],
  ["bull_case", "Bull case"],
  ["bear_case", "Bear case"],
  ["valuation", "Valuation"],
  ["verdict", "Final verdict"],
] as const;

export interface ScreenerDeepDive {
  available: boolean;
  symbol: string;
  reason?: string;
  hint?: string;
  raw?: string;
  verdict?: string | null;
  model?: string | null;
  sections?: Record<string, string>;
  facts?: Record<string, unknown>;
  generated_at?: string | null;
  stale?: boolean;
}

export const screenerApi = {
  ratings: (params: { verdict?: Verdict; sector?: string; sort?: string } = {}) =>
    apiClient
      .get<ScreenerRatingsResponse>("/screener/ratings", { params })
      .then((r) => r.data),
  rating: (symbol: string) =>
    apiClient.get<ScreenerRatingDetail>(`/screener/ratings/${encodeURIComponent(symbol)}`).then((r) => r.data),
  technicalRatings: (params: { verdict?: TechnicalVerdict; sector?: string; sort?: string } = {}) =>
    apiClient
      .get<TechnicalRatingsResponse>("/screener/technical-ratings", { params })
      .then((r) => r.data),
  deepDive: (symbol: string, refresh = false) =>
    apiClient
      .get<ScreenerDeepDive>(`/screener/ratings/${encodeURIComponent(symbol)}/deepdive`, {
        params: refresh ? { refresh: true } : {},
      })
      .then((r) => r.data),
};
