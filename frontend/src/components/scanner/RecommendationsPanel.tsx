import { useState } from "react";
import { Link } from "react-router-dom";

import type { ScanRecommendation } from "@/api/marketScanner";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useScanRecommendations, useScannerStatus, useTriggerScan } from "@/hooks/useMarketScanner";
import { num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const dirTone = (d: string) => (d === "LONG" ? "text-pos" : "text-neg");

function SymbolLabel({ rec, className }: { rec: ScanRecommendation; className?: string }) {
  if (rec.asset_class === "EQUITY") {
    return (
      <Link to={`/stocks/${rec.exchange}/${rec.tradingsymbol}`} className={cn("hover:text-accent", className)}>
        {rec.tradingsymbol}
      </Link>
    );
  }
  return <span className={className}>{rec.tradingsymbol}</span>;
}

const outcomeTone: Record<string, "success" | "destructive" | "warning" | "default"> = {
  TARGET: "success",
  SL: "destructive",
  NEUTRAL: "warning",
  INVALIDATED: "default",
};

function ConfMeter({ value }: { value: number | null }) {
  const v = value ?? 0;
  return (
    <div className="flex items-center gap-1.5" title={`confidence ${num(v, 0)} / 100`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-elevated">
        <div
          className={cn("h-full rounded-full", v >= 70 ? "bg-pos" : v >= 55 ? "bg-amber-400" : "bg-fg-faint")}
          style={{ width: `${Math.max(4, Math.min(100, v))}%` }}
        />
      </div>
      <span className="tabular-nums text-[11px] font-semibold text-fg-muted">{num(v, 0)}</span>
    </div>
  );
}

function ProgressToTarget({ rec }: { rec: ScanRecommendation }) {
  const p = rec.progress;
  if (p == null) return null;
  const pct = Math.max(0, Math.min(100, (p / 1) * 100));
  const past = p < 0;
  return (
    <div className="mt-2">
      <div className="flex justify-between text-[10px] text-fg-faint">
        <span>SL</span>
        <span>entry</span>
        <span>T1</span>
      </div>
      <div className="relative mt-0.5 h-1.5 rounded-full bg-elevated">
        <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
        <div
          className={cn("absolute inset-y-0 rounded-full", past ? "bg-neg" : "bg-pos")}
          style={{
            left: past ? `${50 + pct * 0.5}%` : "50%",
            width: past ? `${Math.min(50, -p * 50)}%` : `${pct * 0.5}%`,
          }}
        />
      </div>
    </div>
  );
}

function Level({ label, value, tone }: { label: string; value: number | null; tone?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span className={cn("tabular-nums text-sm font-semibold", tone)}>{value == null ? "—" : num(value, 2)}</span>
    </div>
  );
}

function OverlayBlock({ o }: { o: NonNullable<ScanRecommendation["option_overlay"]> }) {
  return (
    <div className="mt-2 rounded-md border border-line bg-elevated/50 p-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-fg">
          {o.structure.replace(/_/g, " ")} · {o.expiry} ({o.dte}d)
        </span>
        {o.pop != null && (
          <span className="tabular-nums text-fg-muted">POP {num(o.pop * 100, 0)}%</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-fg-muted">
        {o.legs.map((l) => (
          <span key={l.tradingsymbol} className="tabular-nums">
            {l.side} {l.strike} {l.option_type} @ {num(l.price, 2)}
          </span>
        ))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 tabular-nums text-fg-muted">
        <span>net debit {num(o.net_debit, 2)}</span>
        {o.max_profit != null && <span className="text-pos">max +₹{num(o.max_profit, 0)}</span>}
        {o.max_loss != null && <span className="text-neg">max −₹{num(o.max_loss, 0)}</span>}
        <span>BE {num(o.breakeven, 1)}</span>
        {o.rr != null && <span>R:R {num(o.rr, 2)}</span>}
      </div>
    </div>
  );
}

function LiveCard({ rec }: { rec: ScanRecommendation }) {
  const [open, setOpen] = useState(false);
  const fund = rec.fundamentals as { bias?: string; flags?: string[] } | null;
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("text-xs font-bold", dirTone(rec.direction))}>{rec.direction}</span>
            <SymbolLabel rec={rec} className="truncate font-semibold text-fg" />
            <Badge variant="default" className="shrink-0 text-[10px]">
              {rec.horizon}
            </Badge>
            {rec.tracking_state === "STALE" && (
              <Badge variant="warning" className="shrink-0 text-[10px]">
                price stale
              </Badge>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-muted">{rec.setup_type}</p>
        </div>
        <ConfMeter value={rec.confidence} />
      </div>

      <div className="mt-2 grid grid-cols-4 gap-2">
        <Level label="Entry" value={rec.entry} />
        <Level label="Stop" value={rec.stop_loss} tone="text-neg" />
        <Level label="Target 1" value={rec.target_1} tone="text-pos" />
        <Level label="Target 2" value={rec.target_2} tone="text-pos" />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-muted">
        <span className="tabular-nums">R:R {rec.rr == null ? "—" : num(rec.rr, 2)}</span>
        {rec.risk_pct != null && <span className="tabular-nums">risk {num(rec.risk_pct, 2)}%</span>}
        {rec.pop != null && <span className="tabular-nums">POP {num(rec.pop * 100, 0)}%</span>}
        {rec.last_ltp != null && <span className="tabular-nums">LTP {num(rec.last_ltp, 2)}</span>}
        <span>entry: {rec.entry_type.toLowerCase()}</span>
        {fund?.bias && fund.bias !== "NEUTRAL" && (
          <span className="text-fg-faint">fnd: {fund.bias.replace("SUPPORTIVE_", "").toLowerCase()}</span>
        )}
      </div>

      <ProgressToTarget rec={rec} />

      {rec.setup_tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {rec.setup_tags.slice(0, 8).map((t) => (
            <span key={t} className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-faint">
              {t.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {rec.option_overlay && <OverlayBlock o={rec.option_overlay} />}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-2 text-[11px] font-medium text-accent hover:underline"
      >
        {open ? "Hide" : "Why this trade"} ({rec.factors.length} factors)
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 text-[11px] text-fg-muted">
          {rec.factors.map((f, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className={cn("mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full", f.side === "LONG" ? "bg-pos" : "bg-neg")} />
              <span>
                {f.detail} <span className="text-fg-faint">({f.group}, {f.weight > 0 ? "+" : ""}{num(f.weight, 0)})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] italic text-fg-faint">{rec.disclaimer}</p>
    </div>
  );
}

function ExpiredRow({ rec }: { rec: ScanRecommendation }) {
  return (
    <div className="flex items-center gap-3 border-b border-line/60 px-3 py-2 text-xs last:border-0">
      <Badge variant={outcomeTone[rec.outcome ?? "INVALIDATED"]} className="w-20 shrink-0 justify-center text-[10px]">
        {rec.outcome}
      </Badge>
      <span className={cn("w-12 shrink-0 font-bold", dirTone(rec.direction))}>{rec.direction}</span>
      <SymbolLabel rec={rec} className="w-28 shrink-0 truncate font-medium text-fg" />
      <span className="w-16 shrink-0 text-fg-faint">{rec.horizon.toLowerCase()}</span>
      <span className="flex-1 truncate text-fg-muted">{rec.setup_type}</span>
      <span
        className={cn(
          "w-20 shrink-0 text-right tabular-nums font-semibold",
          (rec.result_pct ?? 0) > 0 ? "text-pos" : (rec.result_pct ?? 0) < 0 ? "text-neg" : "text-fg-muted",
        )}
      >
        {pctSigned(rec.result_pct)}
      </span>
      <span className="w-14 shrink-0 text-right tabular-nums text-fg-faint">
        {rec.result_r == null ? "—" : `${rec.result_r > 0 ? "+" : ""}${num(rec.result_r, 2)}R`}
      </span>
    </div>
  );
}

export function RecommendationsPanel() {
  const { data, isLoading } = useScanRecommendations();
  const { data: status } = useScannerStatus();
  const scan = useTriggerScan();
  const [showExpired, setShowExpired] = useState(true);

  const phase = data?.market_phase ?? "closed";
  const feedStale = status?.tick_feed?.stale;

  const header = (
    <div className="flex flex-wrap items-center gap-2">
      <span>Trade Ideas</span>
      <Badge variant={phase === "open" ? "success" : phase === "tracking_only" ? "warning" : "default"} className="text-[10px]">
        {phase === "open" ? "scanning" : phase === "tracking_only" ? "tracking only" : "market closed"}
      </Badge>
      {feedStale && (
        <Badge variant="warning" className="text-[10px]">
          tick feed stale
        </Badge>
      )}
      {data?.summary && (
        <span className="text-[11px] font-normal text-fg-faint">
          {data.summary.live} live · {data.summary.target}✓ · {data.summary.sl}✗ · {data.summary.neutral}~ today
        </span>
      )}
    </div>
  );

  const actions = (
    <div className="flex items-center gap-2">
      {data?.last_scan?.at && (
        <span className="hidden text-[11px] text-fg-faint sm:inline">
          scanned {data.last_scan.scanned} · {new Date(data.last_scan.at).toLocaleTimeString("en-IN")}
        </span>
      )}
      <Button size="sm" variant="outline" onClick={() => scan.mutate()} disabled={scan.isPending}>
        {scan.isPending ? "Scanning…" : "Scan now"}
      </Button>
    </div>
  );

  return (
    <SectionCard title={header} actions={actions} bodyClassName="p-3">
      {isLoading ? (
        <p className="py-6 text-center text-sm text-fg-faint">Loading recommendations…</p>
      ) : !data?.available ? (
        <p className="py-6 text-center text-sm text-fg-faint">
          {data?.reason ?? "Live market data unavailable — no recommendations."}
        </p>
      ) : data.live.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-faint">
          No high-conviction setups right now.{" "}
          {data.last_scan?.at && `Last scan ${new Date(data.last_scan.at).toLocaleTimeString("en-IN")}.`}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.live.map((r) => (
            <LiveCard key={r.id} rec={r} />
          ))}
        </div>
      )}

      {data && data.expired_today.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowExpired((v) => !v)}
            className="text-xs font-medium text-fg-muted hover:text-fg"
          >
            {showExpired ? "▾" : "▸"} Closed today ({data.expired_today.length})
          </button>
          {showExpired && (
            <div className="mt-1 rounded-md border border-line">
              {data.expired_today.map((r) => (
                <ExpiredRow key={r.id} rec={r} />
              ))}
            </div>
          )}
        </div>
      )}
      <p className="mt-3 text-[10px] text-fg-faint">
        Screener output from technical + price-action + fundamental checks. Not investment advice; no
        guarantee of profit. Confidence is a factor score, not a win rate.
      </p>
    </SectionCard>
  );
}
