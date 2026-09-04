import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { discoveryApi, type SearchParams } from "@/api/discovery";

const KEY = ["discovery"];

export function useDiscoveryUniverse() {
  return useQuery({
    queryKey: [...KEY, "universe"],
    queryFn: discoveryApi.universe,
    staleTime: 5 * 60_000,
  });
}

export function useDiscoveryScreen(currency = "USD") {
  return useQuery({
    queryKey: [...KEY, "screen", currency],
    queryFn: () => discoveryApi.screen(currency),
    staleTime: 5 * 60_000,
  });
}

export function useDiscoveryRuns(limit = 20) {
  return useQuery({
    queryKey: [...KEY, "runs", limit],
    queryFn: () => discoveryApi.runs(limit),
    staleTime: 30_000,
  });
}

export function useRunDiscoverySearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: SearchParams) => discoveryApi.search(params),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, "runs"] }),
  });
}

export function useValidatePortfolio() {
  return useMutation({
    mutationFn: ({
      weights,
      nTrials,
      currency,
    }: {
      weights: Record<string, number>;
      nTrials?: number;
      currency?: string;
    }) => discoveryApi.validate(weights, nTrials ?? 1, currency ?? "USD"),
  });
}
