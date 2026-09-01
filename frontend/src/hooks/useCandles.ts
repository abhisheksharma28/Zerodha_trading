import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import type { Candle } from "@/lib/indicators";

export interface CandlesResponse {
  available: boolean;
  reason?: string;
  symbol: string;
  timeframe: string;
  candles?: Candle[];
}

interface Opts {
  days?: number;
  from?: string;
  to?: string;
}

export function useCandles(symbol: string | undefined, timeframe: string, opts: number | Opts = {}) {
  const o: Opts = typeof opts === "number" ? { days: opts } : opts;
  return useQuery({
    queryKey: ["market", "candles", symbol, timeframe, o.days, o.from, o.to],
    queryFn: () =>
      apiClient
        .get<CandlesResponse>("/market/candles", {
          params: {
            symbol,
            timeframe,
            days: o.days,
            from_date: o.from,
            to_date: o.to,
          },
        })
        .then((r) => r.data),
    enabled: !!symbol,
    staleTime: 20_000,
  });
}
