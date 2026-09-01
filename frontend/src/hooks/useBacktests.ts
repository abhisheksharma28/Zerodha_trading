import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  backtestsApi,
  type CreateBacktestPayload,
  type RunBacktestPayload,
} from "@/api/backtests";

export const backtestKeys = {
  all: ["backtests"] as const,
  detail: (id: string) => ["backtests", id] as const,
};

export function useBacktests() {
  return useQuery({ queryKey: backtestKeys.all, queryFn: backtestsApi.list });
}

export function useBacktest(id: string | undefined) {
  return useQuery({
    queryKey: backtestKeys.detail(id ?? ""),
    queryFn: () => backtestsApi.get(id as string),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.status === "running" || query.state.data?.status === "pending"
        ? 3_000
        : false,
  });
}

export function useCreateBacktest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateBacktestPayload) => backtestsApi.create(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: backtestKeys.all }),
  });
}

export function useRunBacktest(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RunBacktestPayload = {}) => backtestsApi.run(id, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(backtestKeys.detail(id), data);
      queryClient.invalidateQueries({ queryKey: backtestKeys.all });
    },
  });
}
