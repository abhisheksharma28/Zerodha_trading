import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  strategyLibraryApi,
  type BacktestReportPayload,
  type CreateFromTemplatePayload,
} from "@/api/strategyLibrary";
import { strategyKeys } from "@/hooks/useStrategies";

export const strategyLibraryKeys = {
  all: ["strategy-library"] as const,
  detail: (slug: string) => ["strategy-library", slug] as const,
};

export function useStrategyTemplates() {
  return useQuery({
    queryKey: strategyLibraryKeys.all,
    queryFn: strategyLibraryApi.list,
  });
}

export function useStrategyTemplate(slug: string | undefined) {
  return useQuery({
    queryKey: strategyLibraryKeys.detail(slug ?? ""),
    queryFn: () => strategyLibraryApi.get(slug as string),
    enabled: !!slug,
  });
}

export function useCreateStrategyFromTemplate(slug: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateFromTemplatePayload) =>
      strategyLibraryApi.createFromTemplate(slug, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKeys.all }),
  });
}

export function useNifty200Universe() {
  return useQuery({
    queryKey: ["strategy-library", "universe", "nifty200"],
    queryFn: strategyLibraryApi.nifty200,
    staleTime: 24 * 60 * 60_000,
  });
}

export function useBacktestReport(slug: string) {
  return useMutation({
    mutationFn: (payload: BacktestReportPayload) =>
      strategyLibraryApi.backtestReport(slug, payload),
  });
}

export function useDownloadBacktestReportPdf(slug: string) {
  return useMutation({
    mutationFn: (payload: BacktestReportPayload) =>
      strategyLibraryApi.downloadBacktestReportPdf(slug, payload),
  });
}

export function useSeedStrategyLibrary() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: strategyLibraryApi.seed,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKeys.all }),
  });
}
