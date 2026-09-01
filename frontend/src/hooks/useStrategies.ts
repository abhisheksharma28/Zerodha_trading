import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { strategiesApi, type CreateStrategyPayload, type AddVersionPayload } from "@/api/strategies";

export const strategyKeys = {
  all: ["strategies"] as const,
  detail: (id: string) => ["strategies", id] as const,
};

export function useStrategies() {
  return useQuery({ queryKey: strategyKeys.all, queryFn: strategiesApi.list });
}

export function useStrategy(id: string | undefined) {
  return useQuery({
    queryKey: strategyKeys.detail(id ?? ""),
    queryFn: () => strategiesApi.get(id as string),
    enabled: !!id,
  });
}

export function useCreateStrategy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateStrategyPayload) => strategiesApi.create(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKeys.all }),
  });
}

export function useAddStrategyVersion(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddVersionPayload) => strategiesApi.addVersion(strategyId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: strategyKeys.detail(strategyId) });
      queryClient.invalidateQueries({ queryKey: strategyKeys.all });
    },
  });
}
