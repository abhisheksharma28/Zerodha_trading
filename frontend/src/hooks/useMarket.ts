import { useQuery } from "@tanstack/react-query";

import { marketApi } from "@/api/market";

// Near-real-time: the backend hot-caches for ~1.5s so a 2s poll never
// multiplies Kite quote calls. Only refetches while the tab is visible.
export function useMarketOverview(universe = "nifty50") {
  return useQuery({
    queryKey: ["market", "overview", universe],
    queryFn: () => marketApi.overview(universe),
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
}
