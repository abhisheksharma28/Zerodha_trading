import { apiClient } from "@/api/client";

export type Side = "BUY" | "SELL";
export type OrderType = "MARKET" | "LIMIT" | "SL" | "SL-M";
export type Product = "CNC" | "MIS" | "NRML";

export interface PaperSummary {
  account: {
    name: string;
    opening_balance: number;
    invested_capital: number;
    auto_squareoff_mis: boolean;
  };
  funds: { available_margin: number; used_margin: number; total_margin: number };
  pnl: {
    booked: number;
    positions_unrealized: number;
    holdings_unrealized: number;
    holdings_day: number;
    total: number;
    total_pct: number | null;
  };
  charges_paid: number;
  net_worth: number;
  holdings_value: number;
  counts: { positions: number; holdings: number; open_orders: number };
}

export interface PaperPosition {
  id: string;
  exchange: string;
  tradingsymbol: string;
  segment: string | null;
  asset_class: string;
  product: Product;
  net_qty: number;
  buy_qty: number;
  sell_qty: number;
  avg_price: number;
  ltp: number | null;
  prev_close: number | null;
  day_change_pct: number | null;
  realized_pnl: number;
  unrealized_pnl: number;
  pnl: number;
  pnl_pct: number | null;
  margin_blocked: number;
  value: number | null;
  day: boolean;
  status: string;
  opened_at: string | null;
}

export interface PaperHolding {
  id: string;
  exchange: string;
  tradingsymbol: string;
  qty: number;
  t1_qty: number;
  avg_price: number;
  ltp: number | null;
  prev_close: number | null;
  invested: number;
  current_value: number;
  pnl: number;
  pnl_pct: number | null;
  day_pnl: number | null;
  day_change_pct: number | null;
}

export interface PaperOrder {
  id: string;
  created_at: string | null;
  placed_at: string | null;
  filled_at: string | null;
  exchange: string;
  tradingsymbol: string;
  asset_class: string;
  side: Side;
  order_type: OrderType;
  product: Product;
  quantity: number;
  filled_qty: number;
  price: number | null;
  trigger_price: number | null;
  avg_fill_price: number | null;
  status: "OPEN" | "COMPLETE" | "CANCELLED" | "REJECTED";
  status_message: string | null;
  is_squareoff: boolean;
  tag: string | null;
}

export interface PaperTrade {
  id: string;
  order_id: string;
  traded_at: string | null;
  exchange: string;
  tradingsymbol: string;
  asset_class: string;
  product: Product;
  side: Side;
  quantity: number;
  price: number;
  value: number;
  charges: number;
  charges_detail: Record<string, number>;
  realized_pnl: number;
}

export interface PaperLedgerRow {
  id: string;
  at: string | null;
  kind: string;
  amount: number;
  balance_after: number;
  ref: string | null;
  note: string | null;
}

export interface PaperInstrument {
  found: boolean;
  reason?: string;
  exchange: string;
  tradingsymbol: string;
  name: string | null;
  segment: string | null;
  asset_class: "EQUITY" | "FUT" | "OPT";
  lot_size: number;
  tick_size: number;
  ltp: number | null;
  prev_close: number | null;
}

export interface StrategyTemplate {
  slug: string;
  name: string;
  category: string;
  min_instruments: number;
  max_instruments: number | null;
  supported_timeframes: string[];
  params: Record<string, { type: string; default: unknown; description: string; group?: string; choices?: string[]; min?: number; max?: number }>;
  presets: Record<string, Record<string, unknown>>;
  time_horizon: string | null;
  description: string | null;
  warning: string | null;
}

export interface PaperStrategyRun {
  id: string;
  slug: string;
  name: string;
  status: "ACTIVE" | "PAUSED" | "STOPPED";
  instruments: string[];
  timeframe: string;
  product: Product;
  params: Record<string, unknown>;
  flatten_on_stop: boolean;
  started_at: string | null;
  last_tick_at: string | null;
  signals: number;
  orders_placed: number;
  error: string | null;
  trades: number;
  realized_pnl: number;
  charges: number;
  turnover: number;
  open_exposure: Record<string, number>;
}

export interface CreateStrategyBody {
  slug: string;
  name?: string;
  instruments: string[];
  timeframe: string;
  product: Product;
  params?: Record<string, unknown>;
  flatten_on_stop?: boolean;
}

export interface AlgoConfig {
  enabled: boolean;
  min_grade: "A" | "B" | "C";
  pct_per_trade: number;
  max_open_auto: number;
  daily_loss_stop_pct: number;
  cutoff_ist: string;
  allow_delivery: boolean;
  allow_intraday: boolean;
  allow_options: boolean;
  equity_product: "CNC" | "MIS";
  halted_reason: string | null;
  halted_day: string | null;
}

export interface AlgoStatus {
  config: AlgoConfig;
  open_auto_positions: number;
  max_open_auto: number;
  today_realized_pnl: number;
  halted: boolean;
}

export interface PlaceOrderBody {
  exchange: string;
  tradingsymbol: string;
  side: Side;
  quantity: number;
  order_type: OrderType;
  product: Product;
  price?: number | null;
  trigger_price?: number | null;
}

export const paperAccountApi = {
  summary: () => apiClient.get<PaperSummary>("/paper-account/summary").then((r) => r.data),
  positions: () => apiClient.get<PaperPosition[]>("/paper-account/positions").then((r) => r.data),
  holdings: () => apiClient.get<PaperHolding[]>("/paper-account/holdings").then((r) => r.data),
  orders: (status?: string) =>
    apiClient.get<PaperOrder[]>("/paper-account/orders", { params: { status } }).then((r) => r.data),
  trades: () => apiClient.get<PaperTrade[]>("/paper-account/trades").then((r) => r.data),
  ledger: () => apiClient.get<PaperLedgerRow[]>("/paper-account/ledger").then((r) => r.data),
  instrument: (exchange: string, tradingsymbol: string) =>
    apiClient
      .get<PaperInstrument>(`/paper-account/instrument/${exchange}/${encodeURIComponent(tradingsymbol)}`)
      .then((r) => r.data),
  place: (body: PlaceOrderBody) =>
    apiClient.post<PaperOrder>("/paper-account/orders", body).then((r) => r.data),
  modify: (id: string, body: { price?: number; trigger_price?: number; quantity?: number }) =>
    apiClient.put<PaperOrder>(`/paper-account/orders/${id}`, body).then((r) => r.data),
  cancel: (id: string) =>
    apiClient.delete<PaperOrder>(`/paper-account/orders/${id}`).then((r) => r.data),
  exit: (positionId: string) =>
    apiClient.post<PaperOrder>(`/paper-account/positions/${positionId}/exit`).then((r) => r.data),
  addFunds: (amount: number) =>
    apiClient.post<PaperSummary>("/paper-account/funds", { amount }).then((r) => r.data),
  reset: (opening_balance?: number) =>
    apiClient.post<PaperSummary>("/paper-account/reset", { opening_balance }).then((r) => r.data),

  algo: () => apiClient.get<AlgoStatus>("/paper-account/algo").then((r) => r.data),
  setAlgo: (patch: Partial<AlgoConfig>) =>
    apiClient.put<AlgoStatus>("/paper-account/algo", patch).then((r) => r.data),

  strategyRuns: () =>
    apiClient.get<PaperStrategyRun[]>("/paper-account/strategies").then((r) => r.data),
  strategyTemplates: () =>
    apiClient.get<StrategyTemplate[]>("/paper-account/strategies/templates").then((r) => r.data),
  createStrategy: (body: CreateStrategyBody) =>
    apiClient.post<PaperStrategyRun>("/paper-account/strategies", body).then((r) => r.data),
  setStrategyStatus: (id: string, status: string) =>
    apiClient.patch<PaperStrategyRun>(`/paper-account/strategies/${id}`, { status }).then((r) => r.data),
  deleteStrategy: (id: string) => apiClient.delete(`/paper-account/strategies/${id}`).then(() => undefined),
};
