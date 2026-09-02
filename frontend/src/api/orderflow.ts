import { apiClient } from "@/api/client";

export type DataTier =
  | "TRUE_ORDER_FLOW"
  | "ESTIMATED_ORDER_FLOW"
  | "LIMITED_DATA"
  | "UNSUPPORTED";

export interface Capabilities {
  provider: string;
  scope: "live" | "historical";
  tier: DataTier;
  flags: Record<string, boolean | number | string | null>;
  reasons: string[];
  supported: string[];
  unsupported: string[];
}

export interface ProfileLevel {
  price: number;
  volume: number;
  buy_volume: number | null;
  sell_volume: number | null;
  delta: number | null;
}

export interface VolumeProfile {
  bin_size: number;
  levels: ProfileLevel[];
  poc_price: number | null;
  vah_price: number | null;
  val_price: number | null;
  value_area_pct: number;
  hvn_prices: number[];
  lvn_prices: number[];
  total_volume: number;
  bars_used: number;
  source_interval: string;
  tier: DataTier;
  method: string;
  caveats: string[];
}

export interface VolumeProfileResponse {
  available: boolean;
  reason?: string;
  symbol: string;
  timeframe: string;
  candle_count?: number;
  profile?: VolumeProfile;
  capabilities: Capabilities;
}

export interface VwapPoint {
  ts: number;
  vwap: number;
  [band: string]: number;
}

export interface VwapResponse {
  available: boolean;
  reason?: string;
  symbol: string;
  timeframe: string;
  vwap?: {
    anchor_ts: number;
    band_multiples: number[];
    tier: DataTier;
    method: string;
    points: VwapPoint[];
  };
  capabilities: Capabilities;
}

export interface EstimatedDeltaBar {
  ts: number;
  buy_volume: number;
  sell_volume: number;
  delta: number;
  volume: number;
  cvd: number;
  trades: number;
}

export interface EstimatedDeltaResponse {
  tier: DataTier;
  available: boolean;
  reason?: string;
  symbol: string;
  bar_seconds: number;
  samples?: number;
  dropped_opening_slices?: number;
  classification_mix?: Record<string, number>;
  classification_confidence?: number;
  session_cvd?: number;
  current_bar?: { ts: number; buy_volume: number; sell_volume: number; delta: number; volume: number };
  series?: EstimatedDeltaBar[];
  caveats: string[];
  capabilities: Capabilities;
}

interface WindowOpts {
  timeframe?: string;
  days?: number;
  from?: string;
  to?: string;
}

export const orderflowApi = {
  capabilities: (scope: "all" | "live" | "historical" = "all") =>
    apiClient.get("/orderflow/capabilities", { params: { scope } }).then((r) => r.data),

  volumeProfile: (symbol: string, o: WindowOpts & { valueArea?: number; binMultiple?: number } = {}) =>
    apiClient
      .get<VolumeProfileResponse>("/orderflow/volume-profile", {
        params: {
          symbol,
          timeframe: o.timeframe ?? "1m",
          days: o.days,
          from_date: o.from,
          to_date: o.to,
          value_area: o.valueArea,
          bin_multiple: o.binMultiple,
        },
      })
      .then((r) => r.data),

  vwap: (symbol: string, o: WindowOpts & { anchor?: string } = {}) =>
    apiClient
      .get<VwapResponse>("/orderflow/vwap", {
        params: {
          symbol,
          timeframe: o.timeframe ?? "5m",
          days: o.days,
          from_date: o.from,
          to_date: o.to,
          anchor: o.anchor,
        },
      })
      .then((r) => r.data),

  estimatedDelta: (symbol: string, limit = 240) =>
    apiClient
      .get<EstimatedDeltaResponse>("/orderflow/estimated-delta", { params: { symbol, limit } })
      .then((r) => r.data),
};
