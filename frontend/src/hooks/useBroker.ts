import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { brokerApi } from "@/api/broker";

export function useBrokerStatus() {
  return useQuery({
    queryKey: ["broker", "status"],
    queryFn: brokerApi.status,
    refetchInterval: 30_000,
  });
}

export function useExchangeBrokerSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestToken: string) => brokerApi.exchangeSession(requestToken),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["broker", "status"] }),
  });
}
