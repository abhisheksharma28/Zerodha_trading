import { apiClient } from "@/api/client";

export type Weighting = "equal" | "inverse_vol" | "momentum_weighted";
export type RuleType = "none" | "momentum_top_k";
export type Frequency = "weekly" | "monthly" | "quarterly";
export type BasketStatus = "draft" | "deployed" | "archived";

export interface SleeveRule {
  type: RuleType;
  lookback: number;
  top_k: number;
  trend_ma: number;
  min_roc_pct: number;
}

export interface Sleeve {
  id: string;
  name: string;
  weight_pct: number;
  weighting: Weighting;
  members: string[];
  rule: SleeveRule;
}

export interface BasketSpec {
  sleeves: Sleeve[];
}

export interface BacktestSummary {
  generated_at: string | null;
  years: number | null;
  cagr_pct: number | null;
  total_return_pct: number | null;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  annual_turnover_pct: number | null;
}

export interface Basket {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  benchmark: string;
  rebalance_frequency: Frequency;
  drift_band_pct: number;
  capital: number;
  status: BasketStatus;
  paper_account_id: string | null;
  last_rebalanced_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  sleeves: Sleeve[];
  n_sleeves: number;
  backtest_summary: BacktestSummary | null;
  spec?: BasketSpec;
  last_backtest?: BasketBacktest | null;
}

export interface RebalanceSnapshot {
  as_of: string;
  portfolio_value: number;
  weights: Record<string, number>;
  n_orders: number;
  turnover_pct: number;
  cash_pct: number;
  notes: string[];
}

export interface BasketBacktest {
  start: string;
  end: string;
  years: number;
  capital: number;
  benchmark: string;
  frequency: Frequency;
  equity_curve: [string, number][];
  benchmark_curve: [string, number][];
  metrics: Record<string, number | null>;
  rebalances: RebalanceSnapshot[];
  final_holdings: Record<string, number>;
  skipped: { symbol: string; reason: string }[];
  caveats: string[];
  generated_at?: string;
}

export interface TemplateBacktest {
  key: string;
  generated_at: string;
  start: string | null;
  end: string | null;
  years: number | null;
  benchmark: string | null;
  metrics: Record<string, number | null>;
  oos: {
    in_sample: Record<string, number | string | null>;
    out_of_sample: Record<string, number | string | null>;
  };
  regime_breakdown: Record<string, { days: number; return_pct: number | null; ann_vol_pct: number | null }>;
  spark: number[];
}

export interface BasketTemplate {
  key: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  benchmark: string;
  rebalance_frequency: Frequency;
  drift_band_pct: number;
  spec: BasketSpec;
  backtest?: TemplateBacktest;
}

export interface BasketTemplateCatalog {
  categories: string[];
  templates: BasketTemplate[];
  backtests_generated_at: string | null;
}

export interface OrderIntent {
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  est_value: number;
  from_weight: number;
  to_weight: number;
  reason: string;
}

export interface RebalanceResult {
  basket_id: string;
  as_of?: string;
  applied: boolean;
  skipped?: boolean;
  reason?: string;
  portfolio_value?: number;
  basket_cash?: number;
  target_weights?: Record<string, number>;
  orders?: OrderIntent[];
  orders_placed?: number;
  notes?: string[];
}

export interface BasketHoldingRow {
  symbol: string;
  qty: number;
  price: number;
  value: number;
  weight: number;
}

export interface BasketLiveStatus {
  basket_id: string;
  name: string;
  status: BasketStatus;
  frequency: Frequency;
  capital: number;
  portfolio_value: number;
  basket_cash: number;
  invested_value: number;
  return_pct: number | null;
  holdings: BasketHoldingRow[];
  last_rebalanced_at: string | null;
  rebalance_due: boolean;
  events: { as_of: string; mode: string; applied: boolean; n_orders: number; note: string | null }[];
}

export interface BasketEvent {
  id: string;
  as_of: string;
  mode: string;
  applied: boolean;
  target_weights: Record<string, number>;
  orders: OrderIntent[];
  note: string | null;
}

export interface CreateBasketBody {
  name: string;
  description?: string;
  category?: string;
  benchmark?: string;
  rebalance_frequency?: Frequency;
  drift_band_pct?: number;
  capital?: number;
  spec: BasketSpec;
}

export const basketsApi = {
  list: (includeArchived = false) =>
    apiClient
      .get<Basket[]>("/baskets", { params: { include_archived: includeArchived } })
      .then((r) => r.data),

  get: (id: string) => apiClient.get<Basket>(`/baskets/${id}`).then((r) => r.data),

  templates: () =>
    apiClient.get<BasketTemplateCatalog>("/baskets/templates").then((r) => r.data),

  create: (body: CreateBasketBody) =>
    apiClient.post<Basket>("/baskets", body).then((r) => r.data),

  update: (id: string, body: Partial<CreateBasketBody>) =>
    apiClient.put<Basket>(`/baskets/${id}`, body).then((r) => r.data),

  remove: (id: string) =>
    apiClient.delete<{ deleted: boolean; archived?: boolean }>(`/baskets/${id}`).then((r) => r.data),

  backtest: (id: string, years = 5) =>
    apiClient
      .post<BasketBacktest>(`/baskets/${id}/backtest`, null, { params: { years } })
      .then((r) => r.data),

  deploy: (id: string) =>
    apiClient.post<RebalanceResult>(`/baskets/${id}/deploy`).then((r) => r.data),

  undeploy: (id: string, liquidate: boolean) =>
    apiClient
      .post<{ basket_id: string; status: string; positions_sold: number }>(
        `/baskets/${id}/undeploy`,
        { liquidate },
      )
      .then((r) => r.data),

  rebalance: (id: string, force = false) =>
    apiClient
      .post<RebalanceResult>(`/baskets/${id}/rebalance`, null, { params: { force } })
      .then((r) => r.data),

  preview: (id: string) =>
    apiClient.get<RebalanceResult>(`/baskets/${id}/preview`).then((r) => r.data),

  status: (id: string) =>
    apiClient.get<BasketLiveStatus>(`/baskets/${id}/status`).then((r) => r.data),

  events: (id: string, limit = 50) =>
    apiClient.get<BasketEvent[]>(`/baskets/${id}/events`, { params: { limit } }).then((r) => r.data),
};
