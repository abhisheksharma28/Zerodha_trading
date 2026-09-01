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

export function useCandles(symbol: string | undefined, timeframe: string, days?: number) {
  return useQuery({
    queryKey: ["market", "candles", symbol, timeframe, days],
    queryFn: () =>
      apiClient
        .get<CandlesResponse>("/market/candles", { params: { symbol, timeframe, days } })
        .then((r) => r.data),
    enabled: !!symbol,
    staleTime: 20_000,
  });
}
