import { useQuery } from "@tanstack/react-query";

import { marketApi } from "@/api/market";

export function useMarketOverview(universe = "nifty50") {
  return useQuery({
    queryKey: ["market", "overview", universe],
    queryFn: () => marketApi.overview(universe),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}
