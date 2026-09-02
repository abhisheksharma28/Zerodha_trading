import { useQuery } from "@tanstack/react-query";

import { monitoringApi, type LiveIndicators } from "@/api/monitoring";

// Incremental 1-minute indicators maintained server-side off the tick stream
// (never recomputed from history). Returns the entry for one exchange-
// qualified symbol, e.g. "NSE:RELIANCE".
export function useLiveIndicators(symbol: string | undefined): LiveIndicators | null {
  const { data } = useQuery({
    queryKey: ["monitoring", "indicators"],
    queryFn: monitoringApi.indicators,
    refetchInterval: 3_000,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
  if (!symbol || !data) return null;
  return data.instruments[symbol] ?? null;
}
