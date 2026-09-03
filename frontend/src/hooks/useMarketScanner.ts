import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { marketScannerApi, type LogbookFilters } from "@/api/marketScanner";

export function useScanRecommendations(refetchMs = 15_000) {
  return useQuery({
    queryKey: ["market-scanner", "recommendations"],
    queryFn: marketScannerApi.recommendations,
    refetchInterval: refetchMs,
    staleTime: 5_000,
  });
}

export function useScanRecommendation(id: string | null) {
  return useQuery({
    queryKey: ["market-scanner", "recommendation", id],
    queryFn: () => marketScannerApi.recommendation(id as string),
    enabled: !!id,
  });
}

export function useScannerLogbook(filters: LogbookFilters) {
  return useQuery({
    queryKey: ["market-scanner", "logbook", filters],
    queryFn: () => marketScannerApi.logbook(filters),
    staleTime: 30_000,
  });
}

export function useScannerStatus(refetchMs = 20_000) {
  return useQuery({
    queryKey: ["market-scanner", "status"],
    queryFn: marketScannerApi.status,
    refetchInterval: refetchMs,
  });
}

export function useScannerAlerts(refetchMs = 20_000) {
  return useQuery({
    queryKey: ["market-scanner", "alerts"],
    queryFn: () => marketScannerApi.alerts(50, false),
    refetchInterval: refetchMs,
  });
}

export function useTriggerScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: marketScannerApi.scan,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["market-scanner", "recommendations"] });
      qc.invalidateQueries({ queryKey: ["market-scanner", "status"] });
    },
  });
}

export function useMarkAlertsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids?: string[]) => marketScannerApi.markAlertsRead(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["market-scanner", "alerts"] }),
  });
}
