import { useQuery } from "@tanstack/react-query";

import { screenerApi } from "@/api/screener";

export function useScreenerRatings(sort = "score") {
  return useQuery({
    queryKey: ["screener", "ratings", sort],
    queryFn: () => screenerApi.ratings({ sort }),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });
}

export function useScreenerRating(symbol: string | null) {
  return useQuery({
    queryKey: ["screener", "rating", symbol],
    queryFn: () => screenerApi.rating(symbol as string),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  });
}
