import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  strategyLibraryApi,
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

export function useSeedStrategyLibrary() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: strategyLibraryApi.seed,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: strategyKeys.all }),
  });
}
