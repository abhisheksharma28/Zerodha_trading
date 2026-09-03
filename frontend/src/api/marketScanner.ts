import { apiClient } from "@/api/client";

export interface ScanFactor {
  name: string;
  detail: string;
  weight: number;
  side: "LONG" | "SHORT";
  group: string;
}

export interface OptionOverlay {
  structure: string;
  underlying: string;
  expiry: string;
  dte: number;
  lot_size: number;
  legs: {
    tradingsymbol: string;
    strike: number;
    option_type: string;
    side: "BUY" | "SELL";
    price: number;
  }[];
  net_debit: number;
  max_profit_per_unit: number;
  max_loss_per_unit: number;
  max_profit: number | null;
  max_loss: number | null;
  breakeven: number;
  rr: number | null;
  pop: number | null;
  iv: number | null;
  note: string;
}

export interface ScanRecommendation {
  id: string;
  created_at: string | null;
  trading_day: string;
  exchange: string;
  tradingsymbol: string;
  name: string | null;
  segment: string;
  asset_class: "EQUITY" | "INDEX" | "COMMODITY";
  underlying: string | null;
  instrument_token: string;
  horizon: "INTRADAY" | "SWING";
  direction: "LONG" | "SHORT";
  setup_type: string;
  setup_tags: string[];
  ref_price: number | null;
  entry: number | null;
  entry_type: "MARKET" | "LIMIT" | "STOP";
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  rr: number | null;
  risk_pct: number | null;
  atr: number | null;
  confidence: number | null;
  bias_score: number | null;
  pop: number | null;
  factors: ScanFactor[];
  option_overlay: OptionOverlay | null;
  fundamentals: Record<string, unknown> | null;
  status: "LIVE" | "EXPIRED";
  outcome: "TARGET" | "SL" | "NEUTRAL" | "INVALIDATED" | null;
  entered_price: number | null;
  exit_price: number | null;
  exit_at: string | null;
  result_pct: number | null;
  result_r: number | null;
  result_points: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  last_ltp: number | null;
  last_checked_at: string | null;
  tracking_state: "OK" | "STALE";
  progress: number | null;
  disclaimer: string;
}

export interface RecommendationsResponse {
  available: boolean;
  as_of: string;
  market_phase: "open" | "tracking_only" | "closed";
  reason: string | null;
  last_scan: {
    at: string | null;
    scanned: number;
    produced: number;
    universe_size: number;
    elapsed_ms: number | null;
    trigger: string | null;
  } | null;
  summary: {
    live: number;
    expired_today: number;
    target: number;
    sl: number;
    neutral: number;
    invalidated: number;
  };
  live: ScanRecommendation[];
  expired_today: ScanRecommendation[];
}

export interface LogbookResponse {
  total: number;
  page: number;
  page_size: number;
  setups: string[];
  stats: {
    resolved: number;
    target: number;
    sl: number;
    neutral: number;
    win_rate_pct: number | null;
    expectancy_r: number | null;
    avg_win_pct: number | null;
    avg_loss_pct: number | null;
    total_pct: number | null;
    by_setup: Record<string, { n: number; win: number }>;
    by_horizon: Record<string, { n: number; win: number }>;
  };
  rows: ScanRecommendation[];
}

export interface ScannerStatus {
  enabled: boolean;
  market_phase: string;
  scan_interval_s: number;
  track_interval_s: number;
  live_count: number;
  last_run: Record<string, unknown> | null;
  tick_feed: { state: string | null; seconds_since_any_tick: number | null; stale: boolean | null };
}

export interface ScannerAlert {
  id: string;
  created_at: string | null;
  kind: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  read: boolean;
  recommendation_id: string | null;
}

export interface LogbookFilters {
  date_from?: string;
  date_to?: string;
  outcome?: string;
  symbol?: string;
  horizon?: string;
  setup?: string;
  direction?: string;
  page?: number;
  page_size?: number;
}

export const marketScannerApi = {
  recommendations: () =>
    apiClient.get<RecommendationsResponse>("/market-scanner/recommendations").then((r) => r.data),
  recommendation: (id: string) =>
    apiClient.get<ScanRecommendation>(`/market-scanner/recommendations/${id}`).then((r) => r.data),
  logbook: (f: LogbookFilters = {}) =>
    apiClient
      .get<LogbookResponse>("/market-scanner/logbook", { params: f })
      .then((r) => r.data),
  status: () => apiClient.get<ScannerStatus>("/market-scanner/status").then((r) => r.data),
  alerts: (limit = 50, unreadOnly = false) =>
    apiClient
      .get<{ unread: number; alerts: ScannerAlert[] }>("/market-scanner/alerts", {
        params: { limit, unread_only: unreadOnly },
      })
      .then((r) => r.data),
  markAlertsRead: (ids?: string[]) =>
    apiClient.post<{ marked: number }>("/market-scanner/alerts/read", { ids }).then((r) => r.data),
  scan: () => apiClient.post<Record<string, unknown>>("/market-scanner/scan").then((r) => r.data),
};
