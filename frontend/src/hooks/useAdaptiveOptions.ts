import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { adaptiveOptionsApi, type Json } from "@/api/adaptiveOptions";

export function useAdaptiveConfig() {
  return useQuery({
    queryKey: ["adaptive-options", "config"],
    queryFn: adaptiveOptionsApi.config,
    staleTime: 10 * 60_000,
  });
}

export function useAdaptiveExpiries(underlying: string) {
  return useQuery({
    queryKey: ["adaptive-options", "expiries", underlying],
    queryFn: () => adaptiveOptionsApi.expiries(underlying),
    staleTime: 5 * 60_000,
  });
}

export function useAdaptiveIntel(params: {
  underlying: string;
  expiry?: string;
  preset?: string;
  overrides?: Record<string, unknown> | null;
  enabled?: boolean;
  refetchMs?: number;
}) {
  const { enabled = true, refetchMs = 0, ...rest } = params;
  return useQuery({
    queryKey: [
      "adaptive-options",
      "intelligence",
      rest.underlying,
      rest.expiry ?? "auto",
      rest.preset ?? "balanced",
      rest.overrides ?? null,
    ],
    queryFn: () => adaptiveOptionsApi.intelligence(rest),
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: refetchMs > 0 ? refetchMs : false,
  });
}

export function useAdaptiveDecision(params: {
  underlying: string;
  expiry?: string;
  preset?: string;
  overrides?: Json | null;
  compareSlugs?: string[];
  enabled?: boolean;
}) {
  const { enabled = true, ...rest } = params;
  return useQuery({
    queryKey: ["adaptive-options", "decision", rest],
    queryFn: () =>
      adaptiveOptionsApi.decision({
        underlying: rest.underlying,
        expiry: rest.expiry ?? null,
        preset: rest.preset ?? "balanced",
        overrides: rest.overrides ?? null,
        compare_slugs: rest.compareSlugs ?? null,
        record: false,
      }),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useAdaptiveStrategyMatrix(preset = "balanced") {
  return useQuery({
    queryKey: ["adaptive-options", "strategy-matrix", preset],
    queryFn: () => adaptiveOptionsApi.strategyMatrix(preset),
    staleTime: 10 * 60_000,
  });
}

export function useAdaptiveBacktest() {
  return useMutation({ mutationFn: (body: Json) => adaptiveOptionsApi.backtest(body) });
}

export function useAdaptiveValidation() {
  return useMutation({ mutationFn: (body: Json) => adaptiveOptionsApi.validation(body) });
}

export function usePaperRuns() {
  return useQuery({
    queryKey: ["adaptive-options", "paper-runs"],
    queryFn: adaptiveOptionsApi.paperRuns,
    refetchInterval: 20_000,
  });
}

export function usePaperRun(id: string | undefined) {
  return useQuery({
    queryKey: ["adaptive-options", "paper-run", id],
    queryFn: () => adaptiveOptionsApi.paperRun(id as string),
    enabled: !!id,
    refetchInterval: 15_000,
  });
}

export function useStartPaperRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Json) => adaptiveOptionsApi.paperStart(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adaptive-options", "paper-runs"] }),
  });
}

export function usePaperRunAction(id: string) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["adaptive-options", "paper-run", id] });
    qc.invalidateQueries({ queryKey: ["adaptive-options", "paper-runs"] });
  };
  return {
    tick: useMutation({ mutationFn: () => adaptiveOptionsApi.paperTick(id), onSuccess: invalidate }),
    stop: useMutation({ mutationFn: () => adaptiveOptionsApi.paperStop(id), onSuccess: invalidate }),
  };
}
