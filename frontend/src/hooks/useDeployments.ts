import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deploymentsApi, type CreateDeploymentPayload } from "@/api/deployments";

export const deploymentKeys = {
  all: ["deployments"] as const,
  detail: (id: string) => ["deployments", id] as const,
};

export function useDeployments() {
  return useQuery({
    queryKey: deploymentKeys.all,
    queryFn: deploymentsApi.list,
    // Deployments are the "what's happening right now" view — poll so a
    // paused/errored/live deployment's state doesn't go stale silently.
    refetchInterval: 10_000,
  });
}

export function useDeployment(id: string | undefined) {
  return useQuery({
    queryKey: deploymentKeys.detail(id ?? ""),
    queryFn: () => deploymentsApi.get(id as string),
    enabled: !!id,
    refetchInterval: 5_000,
  });
}

export function useCreateDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateDeploymentPayload) => deploymentsApi.create(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: deploymentKeys.all }),
  });
}

function useDeploymentAction(action: (id: string) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => action(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: deploymentKeys.all }),
  });
}

export function useDeployDeployment() {
  return useDeploymentAction(deploymentsApi.deploy);
}
export function usePauseDeployment() {
  return useDeploymentAction(deploymentsApi.pause);
}
export function useResumeDeployment() {
  return useDeploymentAction(deploymentsApi.resume);
}
export function useStopDeployment() {
  return useDeploymentAction(deploymentsApi.stop);
}
