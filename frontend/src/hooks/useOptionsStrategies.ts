import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { optionsStrategiesApi } from "@/api/optionsStrategies";

const keys = {
  template: ["options-strategies", "template"] as const,
  list: ["options-strategies"] as const,
};

export function useOptionsTemplate() {
  return useQuery({ queryKey: keys.template, queryFn: optionsStrategiesApi.template });
}

export function useOptionsInstances() {
  return useQuery({
    queryKey: keys.list,
    queryFn: optionsStrategiesApi.list,
    refetchInterval: 15_000,
  });
}

export function useCreateOptionsInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: optionsStrategiesApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useEvaluateOptionsInstance(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => optionsStrategiesApi.evaluate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useEnterOptionsInstance(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => optionsStrategiesApi.enter(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useExitOptionsInstance(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => optionsStrategiesApi.exit(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.list }),
  });
}
