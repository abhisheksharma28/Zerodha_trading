import { apiClient } from "@/api/client";

export interface ProviderResult<T = unknown> {
  available: boolean;
  source: string;
  fetched_at: string;
  reason: string | null;
  data: T | null;
}

export interface StockQuickLook {
  exchange: string;
  symbol: string;
  instrument: {
    instrument_token: string;
    tradingsymbol: string;
    name?: string | null;
    exchange: string;
    segment?: string;
    instrument_type?: string;
    expiry?: string | null;
    strike?: number | null;
    lot_size?: number | null;
    tick_size?: number | null;
    underlying?: string | null;
  };
  quote:
    | { available: false; reason: string }
    | {
        available: true;
        ltp: number | null;
        open: number | null;
        high: number | null;
        low: number | null;
        prev_close: number | null;
        change: number | null;
        change_pct: number | null;
        volume: number | null;
        avg_price: number | null;
        oi: number | null;
        buy_quantity: number | null;
        sell_quantity: number | null;
        upper_circuit: number | null;
        lower_circuit: number | null;
        last_trade_time: string | null;
        timestamp: string | null;
        depth: {
          buy: { price: number; quantity: number; orders: number }[];
          sell: { price: number; quantity: number; orders: number }[];
        };
      };
  fundamentals_provider: string;
  profile: ProviderResult<Record<string, unknown>>;
  key_metrics: ProviderResult<Record<string, unknown>>;
}

export interface StockFundamentals {
  exchange: string;
  symbol: string;
  provider: string;
  profile: ProviderResult;
  key_metrics: ProviderResult;
  income_statement: ProviderResult;
  quarterly_results: ProviderResult;
  balance_sheet: ProviderResult;
  cash_flow: ProviderResult;
  shareholding: ProviderResult;
  corporate_actions: ProviderResult;
  news: ProviderResult;
}

export const stocksApi = {
  quickLook: (exchange: string, symbol: string) =>
    apiClient
      .get<StockQuickLook>(`/stocks/${exchange}/${encodeURIComponent(symbol)}`)
      .then((r) => r.data),
  fundamentals: (exchange: string, symbol: string) =>
    apiClient
      .get<StockFundamentals>(`/stocks/${exchange}/${encodeURIComponent(symbol)}/fundamentals`)
      .then((r) => r.data),
};
