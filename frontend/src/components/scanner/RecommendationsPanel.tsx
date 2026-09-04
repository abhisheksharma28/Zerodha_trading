import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { ScanRecommendation } from "@/api/marketScanner";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAddIdeaToPaper } from "@/hooks/usePaperAccount";
import { useLiveTicks } from "@/hooks/useLiveTick";
import { useScanRecommendations, useScannerStatus, useTriggerScan } from "@/hooks/useMarketScanner";
import { inr, num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const recSymbol = (r: ScanRecommendation) => `${r.exchange}:${r.tradingsymbol}`;

// Where price sits between SL (−1), entry (0) and T1 (+1), from a live LTP.
// Matches the backend `progress` semantics so the two agree between polls.
function liveProgress(rec: ScanRecommendation, ltp: number): number | null {
  const { entry, stop_loss: sl, target_1: t1 } = rec;
  if (entry == null || sl == null || t1 == null) return null;
  if (rec.direction === "LONG") {
    if (ltp >= entry) return t1 > entry ? (ltp - entry) / (t1 - entry) : null;
    return entry > sl ? -((entry - ltp) / (entry - sl)) : null;
  }
  if (ltp <= entry) return entry > t1 ? (entry - ltp) / (entry - t1) : null;
  return sl > entry ? -((ltp - entry) / (sl - entry)) : null;
}

const dirTone = (d: string) => (d === "LONG" ? "text-pos" : "text-neg");

const STYLE_LABEL: Record<ScanRecommendation["trade_style"], string> = {
  EQUITY_DELIVERY: "Delivery",
  EQUITY_INTRADAY: "Intraday",
  OPTION: "Options",
};
const STYLE_HINT: Record<ScanRecommendation["trade_style"], string> = {
  EQUITY_DELIVERY: "Buy/sell the stock · CNC · hold across days",
  EQUITY_INTRADAY: "Buy/sell the stock · MIS · square off by ~15:20",
  OPTION: "Defined-risk option spread expressing the same view",
};

type FilterKey = "ALL" | "EQUITY_DELIVERY" | "EQUITY_INTRADAY" | "OPTION" | "LONG" | "SHORT";
const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "EQUITY_DELIVERY", label: "Delivery" },
  { key: "EQUITY_INTRADAY", label: "Intraday" },
  { key: "OPTION", label: "Options" },
  { key: "LONG", label: "Long" },
  { key: "SHORT", label: "Short" },
];

const outcomeTone: Record<string, "success" | "destructive" | "warning" | "default"> = {
  TARGET: "success",
  SL: "destructive",
  NEUTRAL: "warning",
  INVALIDATED: "default",
};

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

const GRADE_TONE: Record<string, string> = {
  A: "bg-pos/15 text-pos border-pos/40",
  B: "bg-amber-400/15 text-amber-500 border-amber-400/40",
  C: "bg-fg-faint/10 text-fg-muted border-line",
};

function ScoreBadge({ rec }: { rec: ScanRecommendation }) {
  const [open, setOpen] = useState(false);
  const v = rec.confidence ?? 0;
  const g = rec.grade ?? "C";
  const sd = rec.score_detail;
  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-semibold",
          GRADE_TONE[g],
        )}
        title="score breakdown"
      >
        <span className="text-xs">{g}</span>
        <span className="tabular-nums opacity-80">{num(v, 0)}</span>
      </button>
      {open && sd && (
        <div className="absolute right-0 top-full z-20 mt-1 w-60 rounded-lg border border-line-strong bg-surface p-2.5 text-[11px] shadow-xl">
          <p className="mb-1.5 font-semibold text-fg">
            Score {num(sd.score, 0)}/100 · grade {sd.grade}
            <span className="ml-1 font-normal text-fg-faint">(raw {num(sd.raw, 0)} − pen {num(sd.penalties, 0)})</span>
          </p>
          <ul className="space-y-1">
            {Object.entries(sd.sub_scores).map(([k, val]) => (
              <li key={k} className="flex items-center gap-2">
                <span className="w-16 shrink-0 capitalize text-fg-muted">{k.replace("_", " ")}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
                  <span
                    className={cn("block h-full rounded-full", val >= 0.7 ? "bg-pos" : val >= 0.4 ? "bg-amber-400" : "bg-fg-faint")}
                    style={{ width: `${Math.round(val * 100)}%` }}
                  />
                </span>
                <span className="w-7 shrink-0 text-right tabular-nums text-fg-faint">{Math.round(val * 100)}</span>
                <span className="w-6 shrink-0 text-right tabular-nums text-fg-faint">
                  {Math.round((sd.weights[k] ?? 0) * 100)}%
                </span>
              </li>
            ))}
          </ul>
          {sd.caps.length > 0 && (
            <p className="mt-1.5 text-neg">capped: {sd.caps.join(", ")}</p>
          )}
          <p className="mt-1.5 text-fg-faint">Columns: sub-score / weight. Strict — most ideas sit 45–70.</p>
        </div>
      )}
    </div>
  );
}

// Entry / SL / T1 bar with a live marker that tracks the streaming LTP.
function ProgressToTarget({
  rec,
  liveLtp,
  streaming,
}: {
  rec: ScanRecommendation;
  liveLtp?: number | null;
  streaming?: boolean;
}) {
  const ltp = liveLtp ?? rec.last_ltp ?? null;
  const live = liveLtp != null;
  const p = (ltp != null ? liveProgress(rec, ltp) : null) ?? rec.progress;
  if (p == null && ltp == null) return null;

  // track: SL at 0%, entry at 50%, T1 at 100%
  const clamped = Math.max(-1.15, Math.min(1.15, p ?? 0));
  const markerPct = Math.max(1, Math.min(99, 50 + clamped * 50));
  const adverse = (p ?? 0) < 0;
  const fmt = (v: number | null) => (v == null ? "—" : num(v, 2));

  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between text-[10px] tabular-nums">
        <span className="text-neg">SL {fmt(rec.stop_loss)}</span>
        <span className="text-fg-muted">Entry {fmt(rec.entry)}</span>
        <span className="text-pos">T1 {fmt(rec.target_1)}</span>
      </div>
      <div className="relative h-2 rounded-full bg-elevated">
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line-strong" />
        <div
          className={cn("absolute inset-y-0 rounded-full", adverse ? "bg-neg/70" : "bg-pos/70")}
          style={{ left: adverse ? `${markerPct}%` : "50%", width: `${Math.abs(markerPct - 50)}%` }}
        />
        <div
          className={cn(
            "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface",
            adverse ? "bg-neg" : "bg-pos",
            live && "ring-2 ring-accent/40",
          )}
          style={{ left: `${markerPct}%` }}
          title={ltp != null ? `LTP ${num(ltp, 2)}` : undefined}
        />
      </div>
      <div className="mt-1 text-center text-[10px]">
        <span
          className={cn(
            "tabular-nums font-semibold",
            ltp == null ? "text-fg-faint" : adverse ? "text-neg" : "text-pos",
          )}
        >
          {live && streaming && (
            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-pos align-middle" />
          )}
          LTP {ltp == null ? "—" : num(ltp, 2)}
        </span>
        {p != null && (
          <span className="ml-1 text-fg-faint">
            · {p >= 0 ? "+" : ""}
            {num(p * 100, 0)}% to T1
          </span>
        )}
      </div>
    </div>
  );
}

function Level({ label, value, tone }: { label: string; value: number | null; tone?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span className={cn("tabular-nums text-sm font-semibold", tone)}>
        {value == null ? "—" : num(value, 2)}
      </span>
    </div>
  );
}

function estDays(rec: ScanRecommendation): number | null {
  if (!rec.atr || !rec.entry || !rec.target_1) return null;
  const d = Math.abs(rec.target_1 - rec.entry) / rec.atr;
  return d >= 1 ? Math.round(d) : 1;
}

function Factors({ rec }: { rec: ScanRecommendation }) {
  const [open, setOpen] = useState(false);
  return (
    <>
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
              <span
                className={cn(
                  "mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full",
                  f.side === "LONG" ? "bg-pos" : "bg-neg",
                )}
              />
              <span>
                {f.detail}{" "}
                <span className="text-fg-faint">
                  ({f.group}, {f.weight > 0 ? "+" : ""}
                  {num(f.weight, 0)})
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function AddToPaper({ rec, taken }: { rec: ScanRecommendation; taken: boolean }) {
  const add = useAddIdeaToPaper();
  const done = taken || add.isSuccess;
  const label =
    rec.trade_style === "OPTION" ? "Add spread to paper" : "Add to paper portfolio";
  return (
    <div className="mt-2 flex items-center gap-2">
      <button
        type="button"
        disabled={done || add.isPending}
        onClick={() => add.mutate({ recommendation_id: rec.id })}
        className={cn(
          "rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-colors",
          done
            ? "cursor-default border-pos/40 bg-pos/10 text-pos"
            : "border-accent/50 text-accent hover:bg-accent-soft disabled:opacity-60",
        )}
        title="Place this trade in your paper account — no manual order needed"
      >
        {done ? "✓ In paper portfolio" : add.isPending ? "Adding…" : `＋ ${label}`}
      </button>
      {add.isError && (
        <span className="max-w-[320px] text-[11px] text-neg">
          {(add.error as { response?: { data?: { message?: string; detail?: string } } })?.response
            ?.data?.message ??
            (add.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "Could not add this idea to the paper portfolio."}
        </span>
      )}
    </div>
  );
}

function PairNote({ rec, siblingStyle }: { rec: ScanRecommendation; siblingStyle: string | null }) {
  if (!siblingStyle) return null;
  const other = STYLE_LABEL[siblingStyle as ScanRecommendation["trade_style"]] ?? siblingStyle;
  return (
    <p className="mt-2 rounded bg-elevated/60 px-2 py-1 text-[11px] text-fg-muted">
      ⭑ Same view as the <span className="font-medium text-fg">{other}</span> idea for {rec.tradingsymbol} —
      trade one, not both. To hold them together as a hedge, see the note below.
    </p>
  );
}

function HedgeNote({ rec }: { rec: ScanRecommendation }) {
  const h = rec.hedge;
  if (!h) return null;
  return (
    <div className="mt-2 rounded-md border border-amber-400/30 bg-amber-400/5 p-2 text-[11px]">
      <p className="font-semibold text-amber-600 light:text-amber-700">Hedge (buy in combination)</p>
      <p className="mt-0.5 text-fg-muted">
        Buy the shares <span className="font-medium">and</span> 1 lot ({h.lot_size}) of{" "}
        <span className="tabular-nums">
          {h.expiry} {num(h.strike, 0)} PE
        </span>{" "}
        together — est. ~{inr(h.est_premium_per_lot)} ({num(h.cost_pct, 1)}% of the position). Caps the
        loss near {num(h.floor_price, 0)}. Confirm the live option quote before placing.
      </p>
    </div>
  );
}

function EquityCard({
  rec,
  siblingStyle,
  taken,
  liveLtp,
  streaming,
}: {
  rec: ScanRecommendation;
  siblingStyle: string | null;
  taken: boolean;
  liveLtp?: number | null;
  streaming?: boolean;
}) {
  const fund = rec.fundamentals as { bias?: string } | null;
  const days = rec.trade_style === "EQUITY_DELIVERY" ? estDays(rec) : null;
  const ltp = liveLtp ?? rec.last_ltp ?? null;
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("text-xs font-bold", dirTone(rec.direction))}>
              {rec.direction === "LONG" ? "BUY" : "SELL"}
            </span>
            <SymbolLabel rec={rec} className="truncate font-semibold text-fg" />
            <Badge variant="default" className="shrink-0 text-[10px]" title={STYLE_HINT[rec.trade_style]}>
              {STYLE_LABEL[rec.trade_style]}
            </Badge>
            {rec.tracking_state === "STALE" && (
              <Badge variant="warning" className="shrink-0 text-[10px]">
                price stale
              </Badge>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-muted">{rec.setup_type}</p>
        </div>
        <ScoreBadge rec={rec} />
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
        {ltp != null && (
          <span
            className={cn("tabular-nums", liveLtp != null && streaming && "text-fg")}
            title={liveLtp != null ? "live" : "last checked"}
          >
            LTP {num(ltp, 2)}
          </span>
        )}
        <span>entry: {rec.entry_type.toLowerCase()}</span>
        {days != null && <span>~{days}d to T1</span>}
        {fund?.bias && fund.bias !== "NEUTRAL" && (
          <span className="text-fg-faint">
            fnd: {fund.bias.replace("SUPPORTIVE_", "").toLowerCase()}
          </span>
        )}
      </div>

      <ProgressToTarget rec={rec} liveLtp={liveLtp} streaming={streaming} />

      {rec.status === "LIVE" && <AddToPaper rec={rec} taken={taken} />}

      {rec.setup_tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {rec.setup_tags.slice(0, 8).map((t) => (
            <span key={t} className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-faint">
              {t.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      <HedgeNote rec={rec} />
      <PairNote rec={rec} siblingStyle={siblingStyle} />
      <Factors rec={rec} />
      <p className="mt-2 text-[10px] italic text-fg-faint">{rec.disclaimer}</p>
    </div>
  );
}

function OptionCard({
  rec,
  siblingStyle,
  taken,
  liveLtp,
  streaming,
}: {
  rec: ScanRecommendation;
  siblingStyle: string | null;
  taken: boolean;
  liveLtp?: number | null;
  streaming?: boolean;
}) {
  const o = rec.option_overlay;
  return (
    <div className="rounded-lg border border-accent/30 bg-accent-soft/30 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default" className="shrink-0 text-[10px]">
              OPTIONS
            </Badge>
            <span className={cn("text-xs font-bold", dirTone(rec.direction))}>{rec.direction}</span>
            <SymbolLabel rec={rec} className="truncate font-semibold text-fg" />
            <span className="text-[11px] text-fg-faint">view: {rec.horizon.toLowerCase()}</span>
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-muted">
            {o ? o.structure.replace(/_/g, " ") : rec.setup_type}
            {o ? ` · ${o.expiry} (${o.dte}d)` : ""}
          </p>
        </div>
        <ScoreBadge rec={rec} />
      </div>

      {o && (
        <>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Level label="Net debit" value={o.net_debit} />
            <Level label="Breakeven" value={o.breakeven} />
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Max profit</span>
              <span className="tabular-nums text-sm font-semibold text-pos">
                {o.max_profit == null ? "—" : `+${inr(o.max_profit)}`}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Max loss</span>
              <span className="tabular-nums text-sm font-semibold text-neg">
                {o.max_loss == null ? "—" : `−${inr(o.max_loss)}`}
              </span>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] tabular-nums text-fg-muted">
            {o.legs.map((l) => (
              <span key={l.tradingsymbol}>
                {l.side} {l.strike} {l.option_type} @ {num(l.price, 2)}
              </span>
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-[11px] tabular-nums text-fg-muted">
            {o.pop != null && <span>POP {num(o.pop * 100, 0)}%</span>}
            {o.rr != null && <span>R:R {num(o.rr, 2)}</span>}
            <span>1 lot ({o.lot_size})</span>
          </div>
        </>
      )}

      <p className="mt-2 rounded bg-surface/70 px-2 py-1 text-[11px] text-fg-muted">
        Manage against {rec.tradingsymbol}: exit if it breaks{" "}
        <span className="tabular-nums text-neg">{num(rec.stop_loss, 1)}</span>, book near{" "}
        <span className="tabular-nums text-pos">{num(rec.target_1, 1)}</span>.
      </p>

      <ProgressToTarget rec={rec} liveLtp={liveLtp} streaming={streaming} />

      {rec.status === "LIVE" && <AddToPaper rec={rec} taken={taken} />}

      <PairNote rec={rec} siblingStyle={siblingStyle} />
      <Factors rec={rec} />
      <p className="mt-2 text-[10px] italic text-fg-faint">{rec.disclaimer}</p>
    </div>
  );
}

function Card({
  rec,
  siblingStyle,
  taken,
  liveLtp,
  streaming,
}: {
  rec: ScanRecommendation;
  siblingStyle: string | null;
  taken: boolean;
  liveLtp?: number | null;
  streaming?: boolean;
}) {
  return rec.trade_style === "OPTION" ? (
    <OptionCard
      rec={rec}
      siblingStyle={siblingStyle}
      taken={taken}
      liveLtp={liveLtp}
      streaming={streaming}
    />
  ) : (
    <EquityCard
      rec={rec}
      siblingStyle={siblingStyle}
      taken={taken}
      liveLtp={liveLtp}
      streaming={streaming}
    />
  );
}

function ExpiredRow({ rec }: { rec: ScanRecommendation }) {
  return (
    <div className="flex items-center gap-3 border-b border-line/60 px-3 py-2 text-xs last:border-0">
      <Badge
        variant={outcomeTone[rec.outcome ?? "INVALIDATED"]}
        className="w-20 shrink-0 justify-center text-[10px]"
      >
        {rec.outcome}
      </Badge>
      <span className={cn("w-12 shrink-0 font-bold", dirTone(rec.direction))}>{rec.direction}</span>
      <SymbolLabel rec={rec} className="w-28 shrink-0 truncate font-medium text-fg" />
      <span className="w-16 shrink-0 text-fg-faint">{STYLE_LABEL[rec.trade_style].toLowerCase()}</span>
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

type SortKey = "BEST" | "SCORE" | "RR" | "RISK" | "NEWEST";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "BEST", label: "Best (grade + score)" },
  { key: "SCORE", label: "Score" },
  { key: "RR", label: "Reward : risk" },
  { key: "RISK", label: "Risk % (low first)" },
  { key: "NEWEST", label: "Newest" },
];
const GRADE_RANK: Record<string, number> = { A: 0, B: 1, C: 2 };

export function RecommendationsPanel() {
  const { data, isLoading } = useScanRecommendations();
  const { data: status } = useScannerStatus();
  const scan = useTriggerScan();
  const [showExpired, setShowExpired] = useState(true);
  const [filter, setFilter] = useState<FilterKey>("ALL");
  const [sort, setSort] = useState<SortKey>("BEST");

  const phase = data?.market_phase ?? "closed";
  const feedStale = status?.tick_feed?.stale;
  const paperTaken = useMemo(() => new Set(data?.paper_taken ?? []), [data?.paper_taken]);

  // live LTP stream for every open idea, so the SL/entry/T1 bar tracks price
  // between the 15 s recommendation polls
  const liveSymbols = useMemo(
    () => Array.from(new Set((data?.live ?? []).map(recSymbol))),
    [data?.live],
  );
  const { ticks, status: streamStatus } = useLiveTicks(liveSymbols);
  const streaming = streamStatus === "open";

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of data?.live ?? []) {
      c[r.trade_style] = (c[r.trade_style] ?? 0) + 1;
      c[r.direction] = (c[r.direction] ?? 0) + 1;
    }
    return c;
  }, [data?.live]);

  const siblingStyleFor = useMemo(() => {
    const byPair: Record<string, ScanRecommendation[]> = {};
    for (const r of data?.live ?? []) {
      if (r.pair_id) (byPair[r.pair_id] ??= []).push(r);
    }
    return (r: ScanRecommendation): string | null => {
      if (!r.pair_id) return null;
      const other = (byPair[r.pair_id] ?? []).find((x) => x.id !== r.id);
      return other?.trade_style ?? null;
    };
  }, [data?.live]);

  const shown = useMemo(() => {
    let live = data?.live ?? [];
    if (filter === "LONG" || filter === "SHORT") live = live.filter((r) => r.direction === filter);
    else if (filter !== "ALL") live = live.filter((r) => r.trade_style === filter);
    const cmp: Record<SortKey, (a: ScanRecommendation, b: ScanRecommendation) => number> = {
      BEST: (a, b) =>
        (GRADE_RANK[a.grade ?? "C"] - GRADE_RANK[b.grade ?? "C"]) ||
        (b.confidence ?? 0) - (a.confidence ?? 0) ||
        (b.rr ?? 0) - (a.rr ?? 0),
      SCORE: (a, b) => (b.confidence ?? 0) - (a.confidence ?? 0),
      RR: (a, b) => (b.rr ?? 0) - (a.rr ?? 0),
      RISK: (a, b) => (a.risk_pct ?? 99) - (b.risk_pct ?? 99),
      NEWEST: (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
    };
    return [...live].sort(cmp[sort]);
  }, [data?.live, filter, sort]);

  const header = (
    <div className="flex flex-wrap items-center gap-2">
      <span>Trade Ideas</span>
      <Badge
        variant={phase === "open" ? "success" : phase === "tracking_only" ? "warning" : "default"}
        className="text-[10px]"
      >
        {phase === "open" ? "scanning" : phase === "tracking_only" ? "tracking only" : "market closed"}
      </Badge>
      {feedStale ? (
        <Badge variant="warning" className="text-[10px]">
          tick feed stale
        </Badge>
      ) : streaming && Object.keys(ticks).length > 0 ? (
        <Badge variant="success" className="text-[10px]">
          <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current align-middle" />
          live prices
        </Badge>
      ) : null}
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
      {data && data.available && (data.live.length > 0 || filter !== "ALL") && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {FILTERS.map((f) => {
            const n = f.key === "ALL" ? data.live.length : counts[f.key] ?? 0;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                  filter === f.key
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-line text-fg-muted hover:border-line-strong",
                )}
              >
                {f.label} <span className="tabular-nums opacity-70">{n}</span>
              </button>
            );
          })}
          <label className="ml-auto flex items-center gap-1 text-[11px] text-fg-faint">
            sort
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="rounded-md border border-line bg-surface px-1.5 py-1 text-[11px] text-fg-muted"
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

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
      ) : shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-faint">No {filter.toLowerCase().replace("_", " ")} ideas right now.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((r) => (
            <Card
              key={r.id}
              rec={r}
              siblingStyle={siblingStyleFor(r)}
              taken={paperTaken.has(r.id)}
              liveLtp={ticks[recSymbol(r)]?.ltp ?? null}
              streaming={streaming}
            />
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
