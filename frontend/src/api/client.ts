import axios, { type InternalAxiosRequestConfig } from "axios";

import { record as recordLatency } from "@/lib/clientLatency";

const baseURL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";

export const apiClient = axios.create({ baseURL });

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

// Per-request start time, keyed by the config object axios threads through
// both interceptors — no type augmentation needed.
const started = new WeakMap<InternalAxiosRequestConfig, number>();

function parseServerTiming(header: unknown): number | null {
  if (typeof header !== "string") return null;
  const m = /app;dur=([0-9.]+)/.exec(header);
  return m ? Number(m[1]) : null;
}

apiClient.interceptors.request.use((config) => {
  started.set(config, performance.now());
  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    const t0 = started.get(response.config);
    if (t0 != null) {
      recordLatency(
        response.config.method ?? "get",
        response.config.url ?? "",
        performance.now() - t0,
        parseServerTiming(response.headers?.["server-timing"]),
        true,
      );
      started.delete(response.config);
    }
    return response;
  },
  (error) => {
    const cfg = error?.config as InternalAxiosRequestConfig | undefined;
    const t0 = cfg ? started.get(cfg) : undefined;
    if (cfg && t0 != null) {
      recordLatency(
        cfg.method ?? "get",
        cfg.url ?? "",
        performance.now() - t0,
        parseServerTiming(error?.response?.headers?.["server-timing"]),
        false,
      );
      started.delete(cfg);
    }
    // Backend's AppError handler always returns {code, message, details} —
    // surface `message` consistently so UI error states don't have to know
    // about axios's error shape.
    const body = error?.response?.data as ApiErrorBody | undefined;
    if (body?.message) {
      error.message = body.message;
    }
    return Promise.reject(error);
  },
);
