import { apiClient } from "@/api/client";
import type { Instrument } from "@/types/api";

export interface InstrumentSearchParams {
  q: string;
  exchange?: string;
  segment?: string;
  instrument_type?: string;
  active_only?: boolean;
  limit?: number;
}

export interface OptionStrikeRow {
  strike: number | null;
  option_type: "CE" | "PE";
  tradingsymbol: string;
  instrument_token: string;
  lot_size: number | null;
}

export const instrumentsApi = {
  search: (params: InstrumentSearchParams) =>
    apiClient.get<Instrument[]>("/instruments/search", { params }).then((r) => r.data),
  getByToken: (token: string) =>
    apiClient.get<Instrument>(`/instruments/token/${token}`).then((r) => r.data),
  get: (exchange: string, tradingsymbol: string) =>
    apiClient.get<Instrument>(`/instruments/${exchange}/${tradingsymbol}`).then((r) => r.data),
  underlyings: (exchange = "NFO") =>
    apiClient.get<string[]>("/instruments/underlyings", { params: { exchange } }).then((r) => r.data),
  expiries: (underlying: string, exchange = "NFO") =>
    apiClient
      .get<string[]>(`/instruments/${underlying}/expiries`, { params: { exchange } })
      .then((r) => r.data),
  strikes: (underlying: string, expiry: string, exchange = "NFO") =>
    apiClient
      .get<OptionStrikeRow[]>(`/instruments/${underlying}/strikes`, { params: { expiry, exchange } })
      .then((r) => r.data),
  sync: (exchanges?: string[]) =>
    apiClient
      .post("/instruments/sync", null, { params: exchanges ? { exchanges } : undefined })
      .then((r) => r.data),
};
