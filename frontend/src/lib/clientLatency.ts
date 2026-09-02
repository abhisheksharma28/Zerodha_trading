// Client-observed API latency — "how fast is data updating in the tool".
//
// The axios interceptors (src/api/client.ts) call record() for every request
// with the wall-clock round-trip (request sent -> response received) and, when
// the backend sent a `Server-Timing: app;dur=` header, the server-side handler
// time. This is an external store so a component can subscribe with
// useSyncExternalStore without prop-drilling or context.

import { useSyncExternalStore } from "react";

const RING = 60;

interface Sample {
  ms: number;
  serverMs: number | null;
  at: number;
  ok: boolean;
}

interface UrlStats {
  key: string;
  last_ms: number;
  p50_ms: number;
  p95_ms: number;
  count: number;
}

export interface ClientLatencySnapshot {
  latest: { key: string; ms: number; serverMs: number | null; at: number } | null;
  perUrl: UrlStats[];
}

const rings = new Map<string, Sample[]>();
let latest: ClientLatencySnapshot["latest"] = null;
let snapshot: ClientLatencySnapshot = { latest: null, perUrl: [] };
const listeners = new Set<() => void>();

function pctl(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return sorted[0];
  const rank = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.min(lo + 1, sorted.length - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

function rebuild() {
  const perUrl: UrlStats[] = [];
  for (const [key, samples] of rings) {
    if (samples.length === 0) continue;
    const ordered = samples.map((s) => s.ms).sort((a, b) => a - b);
    perUrl.push({
      key,
      last_ms: samples[samples.length - 1].ms,
      p50_ms: pctl(ordered, 50),
      p95_ms: pctl(ordered, 95),
      count: samples.length,
    });
  }
  perUrl.sort((a, b) => b.count - a.count);
  snapshot = { latest, perUrl };
  for (const l of listeners) l();
}

// Normalise "/market/overview?universe=nifty50" -> "GET /market/overview".
function keyFor(method: string, url: string): string {
  const path = url.split("?")[0].replace(/\/\d+(?=\/|$)/g, "/:id");
  return `${method.toUpperCase()} ${path}`;
}

export function record(
  method: string,
  url: string,
  ms: number,
  serverMs: number | null,
  ok: boolean,
): void {
  const key = keyFor(method, url);
  const arr = rings.get(key) ?? [];
  arr.push({ ms, serverMs, at: Date.now(), ok });
  if (arr.length > RING) arr.shift();
  rings.set(key, arr);
  // The headline follows real data fetches, not the latency poll itself.
  if (!key.includes("/monitoring/latency")) {
    latest = { key, ms, serverMs, at: Date.now() };
  }
  rebuild();
}

export function useClientLatency(): ClientLatencySnapshot {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => snapshot,
    () => snapshot,
  );
}
