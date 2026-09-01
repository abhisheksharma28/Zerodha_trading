// Mirrors backend/app/models/enums.py and backend/app/schemas/*. Kept as
// plain types (not generated) for now — codegen from the OpenAPI schema
// (openapi-typescript) is a natural follow-up once the API surface settles.

export type TradingMode = "backtest" | "simulation" | "paper" | "live";

export type StrategyStatus = "draft" | "active" | "archived";
export type BacktestStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type DeploymentStatus = "pending" | "running" | "paused" | "stopped" | "error";
export type OrderStatus = "PENDING" | "OPEN" | "COMPLETE" | "REJECTED" | "CANCELLED" | "ERROR";

export interface StrategyVersion {
  id: string;
  strategy_id: string;
  version_number: number;
  source_code: string;
  parameters: Record<string, unknown>;
  entry_point: string;
  change_summary: string | null;
  cloned_from_version_id: string | null;
  created_at: string;
}

export interface Strategy {
  id: string;
  name: string;
  description: string | null;
  status: StrategyStatus;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface StrategyDetail extends Strategy {
  versions: StrategyVersion[];
}

export interface Backtest {
  id: string;
  strategy_version_id: string;
  status: BacktestStatus;
  instrument_universe: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  timeframe: string;
  metrics: Record<string, number> | null;
  equity_curve: [string, number][] | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Deployment {
  id: string;
  strategy_version_id: string;
  name: string;
  mode: TradingMode;
  status: DeploymentStatus;
  config: Record<string, unknown>;
  instrument_universe: string[];
  live_trading_confirmed: boolean;
  live_trading_confirmed_at: string | null;
  cloned_from_deployment_id: string | null;
  deployed_at: string | null;
  paused_at: string | null;
  stopped_at: string | null;
  last_heartbeat_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderRow {
  id: string;
  mode: TradingMode;
  deployment_id: string | null;
  backtest_id: string | null;
  broker_order_id: string | null;
  tradingsymbol: string;
  exchange: string;
  transaction_type: "BUY" | "SELL";
  order_type: string;
  product: string;
  variety: string;
  quantity: number;
  price: number | null;
  trigger_price: number | null;
  status: OrderStatus;
  status_message: string | null;
  placed_at: string | null;
  created_at: string;
}

export interface AuditLogRow {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  mode: TradingMode | null;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface ChangeLogEntryRow {
  id: string;
  created_at: string;
  entity_type: string;
  entity_id: string;
  field: string;
  old_value: { value: unknown } | null;
  new_value: { value: unknown } | null;
  changed_by: string;
  reason: string | null;
}

export interface BrokerStatus {
  connected: boolean;
  broker: string;
  kite_user_id: string | null;
  connected_at: string | null;
  expires_at: string | null;
}

// --- Strategy Library ---------------------------------------------------

export interface TemplateParamSpec {
  type: "integer" | "number" | "string" | "boolean" | "enum";
  default: unknown;
  description: string;
  group: "core" | "filter" | "risk" | "sizing";
  min?: number;
  max?: number;
  choices?: unknown[];
}

export interface StrategyTemplateSummary {
  slug: string;
  name: string;
  category: string;
  description: string;
  timeframe: string;
  time_horizon: string;
  complexity: "Low" | "Medium" | "High";
  market_types: string[];
  supports_long: boolean;
  supports_short: boolean;
  supports_intraday: boolean;
  supports_swing: boolean;
  supports_market_neutral: boolean;
  warning: string;
  min_instruments: number;
  max_instruments: number | null;
}

export interface StrategyTemplateDetail extends StrategyTemplateSummary {
  logic: string;
  risks: string[];
  best_for: string;
  required_data: string[];
  example: string;
  parameters: Record<string, TemplateParamSpec>;
  presets: Record<string, Record<string, unknown>>;
}

export interface BacktestReport {
  backtest_id: string;
  status: BacktestStatus;
  instrument_universe: string[];
  timeframe: string;
  initial_capital: number;
  error_message: string | null;
  metrics: Record<string, number | null>;
  cost_config: Record<string, number>;
  cost_breakdown: Record<string, number>;
  data_quality: {
    ok: boolean;
    errors: string[];
    warnings: string[];
    per_symbol: Record<string, unknown>[];
  };
  equity_curve: [string, number][];
  charts: {
    drawdown_curve: [string, number][];
    monthly_returns: Record<string, number>;
    daily_pnl: [string, number][];
    exposure_curve: [string, number][];
    trade_return_distribution: { bin_edges: number[]; counts: number[]; returns: number[] };
  };
  trades: {
    instrument: string;
    direction: "long" | "short";
    quantity: number;
    entry_time: string | null;
    exit_time: string | null;
    entry_price: number;
    exit_price: number;
    gross_pnl: number;
    costs: number;
    net_pnl: number;
    bars_held: number;
    return_pct: number;
    is_open: boolean;
  }[];
}
