import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { paperAccountApi, type AlgoConfig, type PlaceOrderBody } from "@/api/paperAccount";

const KEY = ["paper-account"];

function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: KEY });
}

export function usePaperSummary(refetchMs = 4000) {
  return useQuery({
    queryKey: [...KEY, "summary"],
    queryFn: paperAccountApi.summary,
    refetchInterval: refetchMs,
  });
}

export function usePaperPositions(refetchMs = 4000) {
  return useQuery({
    queryKey: [...KEY, "positions"],
    queryFn: paperAccountApi.positions,
    refetchInterval: refetchMs,
  });
}

export function usePaperHoldings(refetchMs = 6000) {
  return useQuery({
    queryKey: [...KEY, "holdings"],
    queryFn: paperAccountApi.holdings,
    refetchInterval: refetchMs,
  });
}

export function usePaperOrders(refetchMs = 4000) {
  return useQuery({
    queryKey: [...KEY, "orders"],
    queryFn: () => paperAccountApi.orders(),
    refetchInterval: refetchMs,
  });
}

export function usePaperTrades() {
  return useQuery({ queryKey: [...KEY, "trades"], queryFn: paperAccountApi.trades });
}

export function usePaperLedger() {
  return useQuery({ queryKey: [...KEY, "ledger"], queryFn: paperAccountApi.ledger });
}

export function usePaperInstrument(ref: string | null) {
  const [exchange, tradingsymbol] = (ref ?? ":").split(":");
  return useQuery({
    queryKey: [...KEY, "instrument", ref],
    queryFn: () => paperAccountApi.instrument(exchange, tradingsymbol),
    enabled: !!ref && !!tradingsymbol,
    refetchInterval: 3000,
  });
}

export function usePlaceOrder() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (b: PlaceOrderBody) => paperAccountApi.place(b), onSuccess: invalidate });
}

export function useCancelOrder() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (id: string) => paperAccountApi.cancel(id), onSuccess: invalidate });
}

export function useRetryOrder() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (id: string) => paperAccountApi.retry(id), onSuccess: invalidate });
}

export function useExitPosition() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (id: string) => paperAccountApi.exit(id), onSuccess: invalidate });
}

export function useAddFunds() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (amount: number) => paperAccountApi.addFunds(amount), onSuccess: invalidate });
}

export function useResetPaper() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (opening?: number) => paperAccountApi.reset(opening),
    onSuccess: invalidate,
  });
}

export function useReconcilePaper() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: () => paperAccountApi.reconcile(), onSuccess: invalidate });
}

export function useAddIdeaToPaper() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: paperAccountApi.fromIdea,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: ["market-scanner"] });
    },
  });
}

export function usePaperAlgo(refetchMs = 5000) {
  return useQuery({
    queryKey: [...KEY, "algo"],
    queryFn: paperAccountApi.algo,
    refetchInterval: refetchMs,
  });
}

export function useSetPaperAlgo() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (patch: Partial<AlgoConfig>) => paperAccountApi.setAlgo(patch),
    onSuccess: invalidate,
  });
}

export function usePaperStrategyRuns(refetchMs = 5000) {
  return useQuery({
    queryKey: [...KEY, "strategy-runs"],
    queryFn: paperAccountApi.strategyRuns,
    refetchInterval: refetchMs,
  });
}

export function usePaperStrategyTemplates() {
  return useQuery({
    queryKey: [...KEY, "strategy-templates"],
    queryFn: paperAccountApi.strategyTemplates,
    staleTime: 10 * 60_000,
  });
}

export function useCreatePaperStrategy() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: paperAccountApi.createStrategy,
    onSuccess: invalidate,
  });
}

export function useSetPaperStrategyStatus() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      paperAccountApi.setStrategyStatus(id, status),
    onSuccess: invalidate,
  });
}

export function useDeletePaperStrategy() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (id: string) => paperAccountApi.deleteStrategy(id), onSuccess: invalidate });
}
