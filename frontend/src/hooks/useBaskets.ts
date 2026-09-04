import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { basketsApi, type CreateBasketBody } from "@/api/baskets";

const KEY = ["baskets"];

export function useBaskets(includeArchived = false) {
  return useQuery({
    queryKey: [...KEY, { includeArchived }],
    queryFn: () => basketsApi.list(includeArchived),
  });
}

export function useBasket(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => basketsApi.get(id as string),
    enabled: !!id,
  });
}

export function useBasketTemplates(includeInternal = false) {
  return useQuery({
    queryKey: [...KEY, "templates", { includeInternal }],
    queryFn: () => basketsApi.templates(includeInternal),
    staleTime: 30 * 60_000,
  });
}

export function useBasketStatus(id: string | undefined, refetchMs = 15_000) {
  return useQuery({
    queryKey: [...KEY, id, "status"],
    queryFn: () => basketsApi.status(id as string),
    enabled: !!id,
    refetchInterval: refetchMs,
  });
}

export function useBasketEvents(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id, "events"],
    queryFn: () => basketsApi.events(id as string),
    enabled: !!id,
  });
}

export function useBasketUniverses() {
  return useQuery({
    queryKey: [...KEY, "universes"],
    queryFn: () => basketsApi.universes(),
    staleTime: 30 * 60_000,
  });
}

export function useUniverseScreen(name: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "universe-screen", name],
    queryFn: () => basketsApi.universeScreen(name as string),
    enabled: !!name,
    staleTime: 5 * 60_000,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return (id?: string) => {
    qc.invalidateQueries({ queryKey: KEY });
    if (id) qc.invalidateQueries({ queryKey: [...KEY, id] });
  };
}

export function useCreateBasket() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: CreateBasketBody) => basketsApi.create(body),
    onSuccess: () => invalidate(),
  });
}

export function useUpdateBasket(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Partial<CreateBasketBody>) => basketsApi.update(id, body),
    onSuccess: () => invalidate(id),
  });
}

export function useDeleteBasket() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => basketsApi.remove(id),
    onSuccess: () => invalidate(),
  });
}

export function useRunBasketBacktest(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (years: number) => basketsApi.backtest(id, years),
    onSuccess: () => invalidate(id),
  });
}

export function useDeployPreview(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: [...KEY, id, "deploy-preview"],
    queryFn: () => basketsApi.deployPreview(id as string),
    enabled: !!id && enabled,
    staleTime: 20_000,
  });
}

export function useDeployBasket(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (capital?: number) => basketsApi.deploy(id, capital),
    onSuccess: () => invalidate(id),
  });
}

export function useUndeployBasket(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (liquidate: boolean) => basketsApi.undeploy(id, liquidate),
    onSuccess: () => invalidate(id),
  });
}

export function useRebalanceBasket(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (force: boolean) => basketsApi.rebalance(id, force),
    onSuccess: () => invalidate(id),
  });
}
