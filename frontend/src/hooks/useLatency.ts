import { useQuery } from "@tanstack/react-query";

import { monitoringApi } from "@/api/monitoring";

// Live-engine latency snapshot for the "⚡ x.x ms" indicator. Cheap endpoint
// (reads a published snapshot, no broker call), polled while the tab is
// visible.
export function useLatency() {
  return useQuery({
    queryKey: ["monitoring", "latency"],
    queryFn: monitoringApi.latency,
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}
