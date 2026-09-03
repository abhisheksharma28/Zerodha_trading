import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { seasonalityApi } from "@/api/seasonality";

const KEY = ["seasonality"];

export function useSeasonalityReport() {
  return useQuery({
    queryKey: [...KEY, "report"],
    queryFn: seasonalityApi.report,
    staleTime: 10 * 60_000,
  });
}

export function useSeasonalityStatus(enabled = true) {
  return useQuery({
    queryKey: [...KEY, "status"],
    queryFn: seasonalityApi.status,
    refetchInterval: enabled ? 5_000 : false,
  });
}

export function useRefreshSeasonality() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: seasonalityApi.refresh,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useSeasonalityBacktest(params: {
  strategy: string;
  mode: string;
  start_test_year: number;
  long_cost_bps: number;
  short_cost_bps: number;
}) {
  return useQuery({
    queryKey: [...KEY, "backtest", params],
    queryFn: () => seasonalityApi.backtest(params),
    staleTime: 5 * 60_000,
  });
}
