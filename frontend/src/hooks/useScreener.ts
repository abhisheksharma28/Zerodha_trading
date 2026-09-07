import { useMutation, useQuery } from "@tanstack/react-query";

import { screenerApi } from "@/api/screener";

export function useScreenerRatings(sort = "score") {
  return useQuery({
    queryKey: ["screener", "ratings", sort],
    queryFn: () => screenerApi.ratings({ sort }),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });
}

export function useTechnicalRatings(sort = "ta_score") {
  return useQuery({
    queryKey: ["screener", "technical-ratings", sort],
    queryFn: () => screenerApi.technicalRatings({ sort }),
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

/** On-demand narrative deep-dive. `run(symbol)` fetches the cached one or
 *  generates it (slow — an LLM call); `run(symbol, true)` forces a rebuild. */
export function useScreenerDeepDive() {
  return useMutation({
    mutationFn: ({ symbol, refresh }: { symbol: string; refresh?: boolean }) =>
      screenerApi.deepDive(symbol, refresh),
  });
}
