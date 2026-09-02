import { apiClient } from "@/api/client";

export interface LatencyStage {
  stage: string;
  count: number;
  last_ms: number;
  avg_ms: number;
  min_ms: number;
  max_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface LatencySnapshot {
  available: boolean;
  source: "redis" | "in_process";
  stale: boolean;
  age_seconds: number;
  updated_epoch: number;
  latency: {
    stages: Record<string, LatencyStage>;
    headline: {
      idle_ms: number;
      internal_decision_ms: number | null;
      internal_decision_p95_ms: number | null;
      broker_rtt_ms: number | null;
      api_ms: number | null;
      api_p95_ms: number | null;
    };
  };
  engine: {
    running_deployments?: number;
    poll_interval_seconds?: number;
    last_tick_epoch?: number;
    ticker?: {
      state: string;
      detail: string;
      ticker?: {
        connected: boolean;
        subscribed: number;
        mode: string;
        ticks_total: number;
        frames_per_sec: number;
        last_tick_age_seconds: number | null;
        last_error: string | null;
      };
      market_state: {
        instrument_count: number;
        seconds_since_any_tick: number | null;
        stale: boolean;
      };
    };
  };
  thresholds_ms: { excellent: number; fast: number; moderate: number; high: number };
}

export interface LiveIndicators {
  bars: number;
  ema9: number | null;
  ema20: number | null;
  ema50: number | null;
  sma20: number | null;
  rsi14: number | null;
  atr14: number | null;
  vwap: number | null;
  bb_lower: number | null;
  bb_mid: number | null;
  bb_upper: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  roll_low20: number | null;
  roll_high20: number | null;
  last_bar_age_seconds: number | null;
}

export interface IndicatorsResponse {
  interval_seconds: number;
  instruments: Record<string, LiveIndicators>;
}

export interface DeploymentRisk {
  killed: boolean;
  orders_today: number;
  orders_last_minute: number;
  open_positions: Record<string, number>;
  day_realized_pnl: number;
  last_reject: string | null;
}

export interface RiskSnapshot {
  global_kill: boolean;
  deployments: Record<string, DeploymentRisk>;
}

export interface OmsOrder {
  internal_id: string;
  deployment_id: string;
  tradingsymbol: string;
  side: string;
  quantity: number;
  state: string;
  broker_order_id: string | null;
  filled_qty: number;
  avg_fill_price: number | null;
  reject_reason: string | null;
  created_at: string;
  submitted_at: string | null;
  filled_at: string | null;
  latency_ms: {
    create_to_submit: number | null;
    submit_to_ack: number | null;
    submit_to_fill: number | null;
  };
}

export interface OmsSnapshot {
  counts: Record<string, number>;
  open: number;
  orders: OmsOrder[];
}

export const monitoringApi = {
  latency: () => apiClient.get<LatencySnapshot>("/monitoring/latency").then((r) => r.data),
  indicators: () =>
    apiClient.get<IndicatorsResponse>("/monitoring/indicators").then((r) => r.data),
  risk: () => apiClient.get<RiskSnapshot>("/monitoring/risk").then((r) => r.data),
  oms: () => apiClient.get<OmsSnapshot>("/monitoring/oms").then((r) => r.data),
  killSwitch: (scope: string, engaged: boolean) =>
    apiClient
      .post<RiskSnapshot | DeploymentRisk>("/monitoring/risk/kill-switch", { scope, engaged })
      .then((r) => r.data),
};
