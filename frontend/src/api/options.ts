import { apiClient } from "@/api/client";

export interface OptionLeg {
  tradingsymbol: string;
  instrument_token: string;
  ltp: number | null;
  change_pct: number | null;
  oi: number | null;
  volume: number | null;
  iv: number | null;
}
export interface OptionRow {
  strike: number;
  call: OptionLeg | null;
  put: OptionLeg | null;
}
export type OptionChain =
  | { available: false; reason: string; underlying: string; expiry: string }
  | {
      available: true;
      underlying: string;
      expiry: string;
      spot: number | null;
      atm_strike: number | null;
      pcr: number | null;
      max_pain: number | null;
      total_call_oi: number;
      total_put_oi: number;
      rows: OptionRow[];
      as_of: string;
    };

export const optionsApi = {
  underlyings: (exchange = "NFO") =>
    apiClient.get<string[]>("/instruments/underlyings", { params: { exchange } }).then((r) => r.data),
  expiries: (underlying: string, exchange = "NFO") =>
    apiClient
      .get<string[]>(`/instruments/${encodeURIComponent(underlying)}/expiries`, { params: { exchange } })
      .then((r) => r.data),
  chain: (underlying: string, expiry: string) =>
    apiClient
      .get<OptionChain>("/market/option-chain", { params: { underlying, expiry } })
      .then((r) => r.data),
};
