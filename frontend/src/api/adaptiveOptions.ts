import { apiClient } from "@/api/client";

export interface AdaptiveConfigPresets {
  presets: Record<string, Record<string, number | string | boolean>>;
  fields: string[];
  note: string;
}

export interface AdaptiveExpiries {
  underlying: string;
  expiries: string[];
  supported_underlyings: string[];
}

export interface QualityIssue {
  code: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  detail: string;
}

export interface AdaptiveIntel {
  available: boolean;
  reason?: string;
  underlying: string;
  expiry: string;
  dte: number;
  spot: number;
  as_of: string;
  config: Record<string, number | string | boolean> & { preset: string };
  summary: string[];
  regime: {
    label: string;
    direction: string;
    vol_class: string;
    confidence: number;
    stability: number;
    transition_risk: number;
    drivers: string[];
    contributing: Record<string, string>;
  };
  confidence: { score: number; band: string; components: Record<string, number>; notes: string[] };
  pcr: {
    oi_pcr: number;
    volume_pcr: number;
    chg_oi_pcr: number | null;
    atm_pcr: number;
    near_atm_pcr: number;
    weighted_pcr: number;
    state: string;
    transition: string;
    transition_confirmed: boolean;
    price_divergence: string;
    oi_pcr_stat: Record<string, number | null>;
    weighted_stat: Record<string, number | null>;
    history_len: number;
    notes: string[];
  };
  positioning: {
    total_call_oi: number;
    total_put_oi: number;
    call_writing_strength: number;
    put_writing_strength: number;
    call_unwinding: boolean;
    put_unwinding: boolean;
    price_oi_state: string;
    put_support: number | null;
    call_resistance: number | null;
    oi_walls: { strike: number; oi: number; kind: string }[];
    oi_concentration: number;
    oi_migration: string;
    max_pain: number | null;
    notes: string[];
  };
  volatility: {
    atm_iv: number | null;
    call_iv: number | null;
    put_iv: number | null;
    iv_skew: number | null;
    iv_rank: number | null;
    iv_percentile: number | null;
    iv_change: number | null;
    realized_vol: number | null;
    iv_minus_rv: number | null;
    iv_class: string;
    term_structure: string;
    vol_selling_score: number;
    vol_selling_verdict: string;
    history_len: number;
    notes: string[];
  };
  greeks: {
    atm_call: Record<string, number>;
    atm_put: Record<string, number>;
    per_strike: {
      strike: number;
      call: Record<string, number>;
      put: Record<string, number>;
      call_oi: number;
      put_oi: number;
    }[];
    gamma_zone: [number, number] | null;
    notes: string[];
  };
  expected_move: {
    points: number | null;
    upper: number | null;
    lower: number | null;
    pct: number | null;
    by_method: Record<string, number | null>;
    current_move_points: number | null;
    current_vs_expected: number | null;
    notes: string[];
  };
  market_intelligence: {
    trend_direction: string;
    trend_strength: number;
    momentum: string;
    market_structure: string;
    vwap_distance_pct: number;
    above_vwap: boolean;
    ema_stack: string;
    rsi: number | null;
    adx: number | null;
    atr_pct: number | null;
    bb_width_pctile: number | null;
    rel_volume: number | null;
    volume_trend: string;
    price_volume: string;
    prev_day_high: number | null;
    prev_day_low: number | null;
    intraday_high: number | null;
    intraday_low: number | null;
    support: number | null;
    resistance: number | null;
    features: Record<string, number | null>;
  };
  data_quality: {
    score: number;
    ok: boolean;
    issues: QualityIssue[];
    blocking: QualityIssue[];
    underlying_issues: QualityIssue[];
  };
  chain: {
    underlying: string;
    expiry: string;
    spot: number;
    as_of: string;
    dte: number;
    atm: number | null;
    strike_step: number;
    rows: {
      strike: number;
      call_oi: number;
      put_oi: number;
      call_chg_oi: number;
      put_chg_oi: number;
      call_volume: number;
      put_volume: number;
      call_ltp: number | null;
      put_ltp: number | null;
      call_iv: number | null;
      put_iv: number | null;
    }[];
  };
  history_len: number;
  snapshot_recorded: string | null;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Json = Record<string, any>;

export const adaptiveOptionsApi = {
  config: () =>
    apiClient.get<AdaptiveConfigPresets>("/adaptive-options/config").then((r) => r.data),
  expiries: (underlying: string) =>
    apiClient
      .get<AdaptiveExpiries>("/adaptive-options/expiries", { params: { underlying } })
      .then((r) => r.data),
  strategyMatrix: (preset = "balanced") =>
    apiClient
      .get<Json>("/adaptive-options/strategy-matrix", { params: { preset } })
      .then((r) => r.data),
  decision: (body: {
    underlying: string;
    expiry?: string | null;
    preset?: string;
    overrides?: Json | null;
    compare_slugs?: string[] | null;
    record?: boolean;
  }) => apiClient.post<Json>("/adaptive-options/decision", body).then((r) => r.data),
  backtest: (body: Json) =>
    apiClient.post<Json>("/adaptive-options/backtest", body).then((r) => r.data),
  validation: (body: Json) =>
    apiClient.post<Json>("/adaptive-options/validation", body).then((r) => r.data),
  paperStart: (body: Json) =>
    apiClient.post<Json>("/adaptive-options/paper/runs", body).then((r) => r.data),
  paperRuns: () =>
    apiClient.get<Json>("/adaptive-options/paper/runs").then((r) => r.data),
  paperRun: (id: string) =>
    apiClient.get<Json>(`/adaptive-options/paper/runs/${id}`).then((r) => r.data),
  paperTick: (id: string) =>
    apiClient.post<Json>(`/adaptive-options/paper/runs/${id}/tick`).then((r) => r.data),
  paperStop: (id: string) =>
    apiClient.post<Json>(`/adaptive-options/paper/runs/${id}/stop`).then((r) => r.data),
  paperDecisions: (id: string, limit = 200) =>
    apiClient
      .get<Json>(`/adaptive-options/paper/runs/${id}/decisions`, { params: { limit } })
      .then((r) => r.data),
  intelligence: (params: {
    underlying: string;
    expiry?: string;
    preset?: string;
    overrides?: Record<string, unknown> | null;
    record?: boolean;
  }) => {
    if (params.overrides && Object.keys(params.overrides).length) {
      return apiClient
        .post<AdaptiveIntel>("/adaptive-options/intelligence", {
          underlying: params.underlying,
          expiry: params.expiry ?? null,
          preset: params.preset ?? "balanced",
          overrides: params.overrides,
          record: params.record ?? true,
        })
        .then((r) => r.data);
    }
    return apiClient
      .get<AdaptiveIntel>("/adaptive-options/intelligence", {
        params: {
          underlying: params.underlying,
          expiry: params.expiry,
          preset: params.preset ?? "balanced",
          record: params.record ?? true,
        },
      })
      .then((r) => r.data);
  },
};
