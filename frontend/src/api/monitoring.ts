import { apiClient } from "@/api/client";

export interface LatencyStage {
  stage: string;
  count: number;
  last_ms: number;
  avg_ms: number;
  min_ms: number;
  max_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface LatencySnapshot {
  available: boolean;
  source: "redis" | "in_process";
  stale: boolean;
  age_seconds: number;
  updated_epoch: number;
  latency: {
    stages: Record<string, LatencyStage>;
    headline: {
      idle_ms: number;
      internal_decision_ms: number | null;
      internal_decision_p95_ms: number | null;
      broker_rtt_ms: number | null;
    };
  };
  engine: {
    running_deployments?: number;
    poll_interval_seconds?: number;
    last_tick_epoch?: number;
  };
  thresholds_ms: { excellent: number; fast: number; moderate: number; high: number };
}

export const monitoringApi = {
  latency: () =>
    apiClient.get<LatencySnapshot>("/monitoring/latency").then((r) => r.data),
};
