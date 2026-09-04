import { apiClient } from "@/api/client";

export interface InsightIndex {
  ltp: number | null;
  change_pct: number | null;
}

export interface MarketRegime {
  available: boolean;
  regime?: "strong_bull" | "bull" | "neutral" | "caution" | "risk_off";
  score?: number;
  drivers?: string[];
  signals?: Record<string, number>;
  index?: string;
  as_of?: string;
  reason?: string;
}

export interface InsightPulse {
  nifty: InsightIndex;
  bank: InsightIndex;
  vix: number | null;
  vol_regime: string;
  vol_regime_why: string;
  risk_tone: string;
  risk_tone_why: string;
  market_regime?: MarketRegime;
  breadth: {
    advances: number;
    declines: number;
    unchanged: number;
    total: number;
    ad_ratio: number | null;
  };
  indices: { symbol: string; ltp: number | null; change_pct: number | null; group?: string }[];
  signals: Record<string, string[]>;
}

export interface SectorRow {
  sector: string;
  count: number;
  advances: number;
  declines: number;
  avg_change_pct: number;
}

export interface MoverRow {
  symbol: string;
  name?: string;
  ltp?: number | null;
  change_pct?: number | null;
  value?: number;
}

export interface ScannerIdea {
  symbol: string;
  direction: "LONG" | "SHORT";
  style: string | null;
  setup: string | null;
  grade: string | null;
  confidence: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  rr: number | null;
}

export interface InsightsBriefing {
  available: boolean;
  reason?: string;
  as_of: string;
  universe?: string;
  headline?: string;
  bullets?: string[];
  pulse?: InsightPulse;
  sectors?: { leaders: SectorRow[]; laggards: SectorRow[]; all: SectorRow[] };
  movers?: { gainers: MoverRow[]; losers: MoverRow[]; most_active: MoverRow[] };
  scanner?: {
    available: boolean;
    live?: number;
    long?: number;
    short?: number;
    long_pct?: number | null;
    top_sectors?: [string, number][];
    top_ideas?: ScannerIdea[];
    last_scan?: string | null;
  };
  book?: {
    available: boolean;
    net_worth?: number;
    total_pnl?: number;
    total_pnl_pct?: number;
    day_pnl?: number;
    available_margin?: number;
    counts?: { positions: number; holdings: number; open_orders: number };
    movers?: { symbol: string; day_change_pct: number; pnl_pct: number | null }[];
    deployed_baskets?: {
      id: string;
      name: string;
      category?: string | null;
      value?: number;
      return_pct?: number | null;
      rebalance_due?: boolean;
    }[];
    alerts?: string[];
  };
  seasonality?: {
    month?: string;
    anchor?: string | null;
    historical_long_tilt?: string[];
    historical_short_tilt?: string[];
    verdict?: string;
    caveat?: string;
  } | null;
}

export const insightsApi = {
  get: (universe: "nifty50" | "nifty100" | "nifty200" = "nifty100", fresh = false) =>
    apiClient
      .get<InsightsBriefing>("/insights", { params: { universe, fresh } })
      .then((r) => r.data),
};
