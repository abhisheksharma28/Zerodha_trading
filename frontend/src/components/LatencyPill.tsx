import { useState } from "react";
import { Zap } from "lucide-react";

import { useLatency } from "@/hooks/useLatency";
import { useClientLatency } from "@/lib/clientLatency";
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

// Client round-trip is network + server + parse — tens of ms locally, more
// over a real network. Different scale from the sub-ms internal engine bands.
const CLIENT_BANDS = [
  { max: 10, label: "Excellent", cls: "text-pos" },
  { max: 30, label: "Fast", cls: "text-pos" },
  { max: 100, label: "Moderate", cls: "text-accent" },
  { max: 300, label: "Slow", cls: "text-neg" },
  { max: Infinity, label: "Very slow", cls: "text-neg" },
];

function fmtMs(ms: number): string {
  if (ms >= 100) return `${ms.toFixed(0)} ms`;
  if (ms >= 10) return `${ms.toFixed(1)} ms`;
  return `${ms.toFixed(2)} ms`;
}

function clientBand(ms: number) {
  return CLIENT_BANDS.find((b) => ms < b.max) ?? CLIENT_BANDS[CLIENT_BANDS.length - 1];
}

export function LatencyPill() {
  const { data: engine } = useLatency();
  const client = useClientLatency();
  const [open, setOpen] = useState(false);

  const latest = client.latest;
  const headlineMs = latest?.ms ?? null;
  const b = headlineMs != null ? clientBand(headlineMs) : null;

  const engineStages = engine?.available ? engine.latency.stages : {};
  const ticker = engine?.engine.ticker;
  const engineHeadline = engine?.available ? engine.latency.headline : null;

  return (
    <div
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1 text-xs font-medium",
          b ? b.cls : "text-fg-faint",
        )}
        title="Data-refresh latency for this tool (request round-trip). Tap for the breakdown."
      >
        <Zap className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-[3.75rem] text-right tabular-nums">
          {headlineMs != null ? fmtMs(headlineMs) : "— ms"}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-[19rem] max-w-[calc(100vw-1.5rem)] rounded-lg border border-line-strong bg-surface p-3 text-xs shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-fg">Latency monitor</span>
            {b && <span className={cn("font-medium", b.cls)}>{b.label}</span>}
          </div>

          {/* --- what the user asked for: data refresh speed --- */}
          <p className="text-[10px] uppercase tracking-wide text-fg-faint">Data refresh (this browser)</p>
          {latest ? (
            <div className="mt-1">
              <div className="flex justify-between">
                <span className="truncate text-fg-muted">{latest.key}</span>
                <span className="tabular-nums">{fmtMs(latest.ms)}</span>
              </div>
              {latest.serverMs != null && (
                <div className="flex justify-between text-fg-faint">
                  <span>server</span>
                  <span className="tabular-nums">
                    {fmtMs(latest.serverMs)} · network {fmtMs(Math.max(0, latest.ms - latest.serverMs))}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="mt-1 text-[11px] text-fg-faint">Waiting for the first request…</p>
          )}

          {client.perUrl.length > 0 && (
            <table className="mt-2 w-full tabular-nums">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-fg-faint">
                  <th className="pb-1 text-left font-medium">Endpoint</th>
                  <th className="pb-1 text-right font-medium">Last</th>
                  <th className="pb-1 text-right font-medium">p95</th>
                </tr>
              </thead>
              <tbody>
                {client.perUrl.slice(0, 6).map((u) => (
                  <tr key={u.key}>
                    <td className="max-w-[9rem] truncate py-0.5 text-left text-fg-muted">
                      {u.key.replace(/^GET /, "")}
                    </td>
                    <td className="py-0.5 text-right">{fmtMs(u.last_ms)}</td>
                    <td className="py-0.5 text-right text-fg-faint">{fmtMs(u.p95_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* --- internal engine pipeline (only once it has samples) --- */}
          {engine?.available && Object.keys(engineStages).length > 0 && (
            <>
              <p className="mt-3 text-[10px] uppercase tracking-wide text-fg-faint">
                Internal engine (server-side)
              </p>
              <table className="mt-1 w-full tabular-nums">
                <tbody>
                  {["api", "market_data", "strategy_eval", "risk", "order_prep", "internal_decision"]
                    .filter((k) => engineStages[k])
                    .map((k) => (
                      <tr key={k}>
                        <td className="py-0.5 text-left text-fg-muted">{STAGE_LABELS[k] ?? k}</td>
                        <td className="py-0.5 text-right">{fmtMs(engineStages[k].last_ms)}</td>
                        <td className="py-0.5 text-right text-fg-faint">
                          {fmtMs(engineStages[k].p95_ms)}
                        </td>
                      </tr>
                    ))}
                  {engineStages.broker_rtt && (
                    <tr>
                      <td className="py-0.5 text-left text-fg-muted">
                        {STAGE_LABELS.broker_rtt}
                        <span className="ml-1 rounded bg-elevated px-1 text-[9px] uppercase text-fg-faint">
                          external
                        </span>
                      </td>
                      <td className="py-0.5 text-right">{fmtMs(engineStages.broker_rtt.last_ms)}</td>
                      <td className="py-0.5 text-right text-fg-faint">
                        {fmtMs(engineStages.broker_rtt.p95_ms)}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )}

          {engineHeadline?.api_ms != null && !engine?.latency.stages.api && (
            <p className="mt-2 text-[10px] text-fg-faint">
              server handler: {fmtMs(engineHeadline.api_ms)} (p95 {fmtMs(engineHeadline.api_p95_ms ?? 0)})
            </p>
          )}

          {ticker && (
            <p className="mt-2 text-[10px] text-fg-faint">
              ticker: {ticker.state}
              {ticker.ticker &&
                ` · ${ticker.ticker.connected ? "connected" : "down"} · ${
                  ticker.ticker.frames_per_sec
                }/s · ${ticker.market_state.instrument_count} instruments`}
              {ticker.market_state.stale && " · STALE"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
