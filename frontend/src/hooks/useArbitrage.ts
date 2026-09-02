import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { arbitrageApi } from "@/api/arbitrage";

const K = ["arbitrage"] as const;

export function useArbLibrary() {
  return useQuery({ queryKey: [...K, "library"], queryFn: arbitrageApi.library, staleTime: 3_600_000 });
}

export function useArbStrategy(slug: string | undefined) {
  return useQuery({
    queryKey: [...K, "strategy", slug],
    queryFn: () => arbitrageApi.strategy(slug as string),
    enabled: !!slug,
  });
}

export function useArbBacktests() {
  return useQuery({ queryKey: [...K, "backtests"], queryFn: arbitrageApi.listBacktests });
}

export function useRunArbBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: arbitrageApi.runBacktest,
    onSuccess: () => qc.invalidateQueries({ queryKey: K }),
  });
}

export function useLatestDiscovery() {
  return useQuery({ queryKey: [...K, "discovery"], queryFn: arbitrageApi.latestDiscovery });
}

export function useRunPairDiscovery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: arbitrageApi.pairDiscovery,
    onSuccess: () => qc.invalidateQueries({ queryKey: [...K, "discovery"] }),
  });
}

export function useArbPortfolio() {
  return useQuery({ queryKey: [...K, "portfolio"], queryFn: arbitrageApi.portfolio });
}

export function useArbScanner() {
  return useQuery({ queryKey: [...K, "scanner"], queryFn: arbitrageApi.scanner });
}
