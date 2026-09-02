import { useState } from "react";
import { Zap } from "lucide-react";

import { useLatency } from "@/hooks/useLatency";
import type { LatencySnapshot } from "@/api/monitoring";
import { cn } from "@/lib/utils";

const STAGE_LABELS: Record<string, string> = {
  market_data: "Market data",
  strategy_eval: "Strategy eval",
  risk: "Risk engine",
  order_prep: "Order prep",
  order_dispatch: "Order dispatch",
  internal_decision: "Internal decision",
  broker_rtt: "Broker round-trip",
};

// Fixed-width so the value never shifts the layout as it changes.
function fmtMs(ms: number): string {
  if (ms >= 100) return `${ms.toFixed(0)} ms`;
  if (ms >= 10) return `${ms.toFixed(1)} ms`;
  return `${ms.toFixed(2)} ms`;
}

function band(ms: number, t: LatencySnapshot["thresholds_ms"]) {
  if (ms < t.excellent) return { label: "Excellent", cls: "text-pos" };
  if (ms < t.fast) return { label: "Fast", cls: "text-pos" };
  if (ms < t.moderate) return { label: "Moderate", cls: "text-accent" };
  if (ms < t.high) return { label: "High", cls: "text-neg" };
  return { label: "Very high", cls: "text-neg" };
}

export function LatencyPill() {
  const { data } = useLatency();
  const [open, setOpen] = useState(false);

  if (!data || !data.available) {
    return (
      <span
        className="hidden items-center gap-1 text-xs text-fg-faint md:flex"
        title="Live engine idle — start a strategy deployment to see decision latency."
      >
        <Zap className="h-3.5 w-3.5" />
        <span className="tabular-nums">— ms</span>
      </span>
    );
  }

  const hl = data.latency.headline;
  const isDecision = hl.internal_decision_ms != null;
  const value = isDecision ? (hl.internal_decision_ms as number) : hl.idle_ms;
  const b = band(value, data.thresholds_ms);
  const stages = data.latency.stages;

  return (
    <div
      className="relative hidden md:block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn("flex items-center gap-1 text-xs font-medium", b.cls)}
        title="Internal engine latency (excludes broker round-trip). Click for the breakdown."
      >
        <Zap className="h-3.5 w-3.5" />
        <span className="min-w-[3.75rem] text-right tabular-nums">{fmtMs(value)}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-72 rounded-lg border border-line-strong bg-surface p-3 text-xs shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-fg">Latency monitor</span>
            <span className={cn("font-medium", b.cls)}>{b.label}</span>
          </div>

          <p className="mb-2 text-[11px] text-fg-faint">
            {isDecision
              ? "Showing tick → order-sent (internal decision)."
              : "Showing market-data + strategy-eval (idle engine cost)."}
          </p>

          <table className="w-full tabular-nums">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-fg-faint">
                <th className="pb-1 text-left font-medium">Stage</th>
                <th className="pb-1 text-right font-medium">Last</th>
                <th className="pb-1 text-right font-medium">p95</th>
              </tr>
            </thead>
            <tbody>
              {["market_data", "strategy_eval", "risk", "order_prep", "order_dispatch", "internal_decision"]
                .filter((k) => stages[k])
                .map((k) => (
                  <tr key={k}>
                    <td className="py-0.5 text-left text-fg-muted">{STAGE_LABELS[k] ?? k}</td>
                    <td className="py-0.5 text-right">{fmtMs(stages[k].last_ms)}</td>
                    <td className="py-0.5 text-right text-fg-faint">{fmtMs(stages[k].p95_ms)}</td>
                  </tr>
                ))}
            </tbody>
            {stages.broker_rtt && (
              <tbody className="border-t border-line">
                <tr>
                  <td className="py-0.5 text-left text-fg-muted">
                    {STAGE_LABELS.broker_rtt}
                    <span className="ml-1 rounded bg-elevated px-1 text-[9px] uppercase text-fg-faint">
                      external
                    </span>
                  </td>
                  <td className="py-0.5 text-right">{fmtMs(stages.broker_rtt.last_ms)}</td>
                  <td className="py-0.5 text-right text-fg-faint">
                    {fmtMs(stages.broker_rtt.p95_ms)}
                  </td>
                </tr>
              </tbody>
            )}
          </table>

          <p className="mt-2 text-[10px] text-fg-faint">
            source: {data.source}
            {data.stale && " · stale"}
            {data.engine.running_deployments != null &&
              ` · ${data.engine.running_deployments} deployment(s)`}
          </p>
        </div>
      )}
    </div>
  );
}
