import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { insightsApi } from "@/api/insights";

const KEY = ["insights"];

export function useInsights(universe: "nifty50" | "nifty100" | "nifty200" = "nifty100") {
  return useQuery({
    queryKey: [...KEY, universe],
    queryFn: () => insightsApi.get(universe),
    refetchInterval: 60_000,
    staleTime: 45_000,
  });
}

export function useRefreshInsights(universe: "nifty50" | "nifty100" | "nifty200" = "nifty100") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => insightsApi.get(universe, true),
    onSuccess: (data) => qc.setQueryData([...KEY, universe], data),
  });
}
