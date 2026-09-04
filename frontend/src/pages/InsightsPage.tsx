import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, RefreshCw } from "lucide-react";

import type { InsightsBriefing, MoverRow, ScannerIdea, SectorRow } from "@/api/insights";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { useInsights, useRefreshInsights } from "@/hooks/useInsights";
import { inr, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const short = (s: string) => s.replace(/^NIFTY /, "");
const sgn = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${num(v, d)}`;

const TONE_CLS: Record<string, string> = {
  "risk-on": "bg-pos/15 text-pos border-pos/40",
  resilient: "bg-pos/10 text-pos border-pos/30",
  "range-bound": "bg-elevated text-fg-muted border-line",
  mixed: "bg-elevated text-fg-muted border-line",
  "narrow / thin": "bg-amber-400/15 text-amber-500 border-amber-400/40",
  "risk-off": "bg-neg/15 text-neg border-neg/40",
};

export default function InsightsPage() {
  const [universe, setUniverse] = useState<"nifty50" | "nifty100" | "nifty200">("nifty100");
  const { data, isLoading } = useInsights(universe);
  const refresh = useRefreshInsights(universe);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Market Insights"
        subtitle="One read of the whole board — pulse, sectors, what the scanner sees, your book — so you don't have to walk every tab."
        actions={
          <div className="flex items-center gap-2">
            <select
              className="h-8 rounded-md border border-line bg-surface px-2 text-xs"
              value={universe}
              onChange={(e) => setUniverse(e.target.value as typeof universe)}
            >
              <option value="nifty50">Nifty 50</option>
              <option value="nifty100">Nifty 100</option>
              <option value="nifty200">Nifty 200</option>
            </select>
            <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
              {refresh.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
              )}
              Refresh
            </Button>
          </div>
        }
      />

      {isLoading && <p className="py-10 text-center text-sm text-fg-faint">Reading the board…</p>}

      {data && !data.available && (
        <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-600 dark:text-amber-400">
          {data.reason ?? "Market data is unavailable — check the broker session."}
        </div>
      )}

      {data?.available && <Briefing data={data} />}
    </div>
  );
}

function Briefing({ data }: { data: InsightsBriefing }) {
  const nav = useNavigate();
  const p = data.pulse!;
  const tone = p.risk_tone;
  const brd = p.breadth;
  const total = Math.max(brd.total, 1);

  return (
    <>
      {/* hero */}
      <div className="rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded-md border px-2 py-0.5 text-xs font-bold uppercase tracking-wide",
              TONE_CLS[tone] ?? TONE_CLS.mixed,
            )}
          >
            {tone}
          </span>
          <span className="text-xs text-fg-faint">
            {p.vol_regime} volatility · India VIX {num(p.vix, 2)} ·{" "}
            {data.as_of ? new Date(data.as_of).toLocaleTimeString("en-IN") : ""}
          </span>
        </div>
        <p className="mt-2 max-w-4xl text-[13px] leading-relaxed text-fg">
          {renderBold(data.headline ?? "")}
        </p>
        {data.bullets && data.bullets.length > 0 && (
          <ul className="mt-2 space-y-1">
            {data.bullets.map((b, i) => (
              <li key={i} className="text-[12px] text-fg-muted">
                • {b}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* pulse */}
        <SectionCard title="Market pulse" index={1}>
          <div className="flex flex-col gap-3 p-4">
            <div className="grid grid-cols-3 gap-3">
              <Mini label="Nifty 50" value={num(p.nifty.ltp, 0)} sub={`${sgn(p.nifty.change_pct)}%`} tone={p.nifty.change_pct} />
              <Mini label="Bank Nifty" value={num(p.bank.ltp, 0)} sub={`${sgn(p.bank.change_pct)}%`} tone={p.bank.change_pct} />
              <Mini label="India VIX" value={num(p.vix, 2)} sub={p.vol_regime} />
            </div>
            <div>
              <div className="flex justify-between text-[11px] text-fg-faint">
                <span className="text-pos">{brd.advances} advancing</span>
                <span>A/D {brd.ad_ratio ?? "—"}</span>
                <span className="text-neg">{brd.declines} declining</span>
              </div>
              <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-elevated">
                <div className="bg-pos" style={{ width: `${(brd.advances / total) * 100}%` }} />
                <div className="bg-line" style={{ width: `${(brd.unchanged / total) * 100}%` }} />
                <div className="bg-neg" style={{ width: `${(brd.declines / total) * 100}%` }} />
              </div>
            </div>
            <p className="text-[11px] text-fg-faint">{p.vol_regime_why}</p>
            {(p.signals?.gap_up?.length || p.signals?.gap_down?.length) && (
              <p className="text-[11px] text-fg-muted">
                {p.signals.gap_up?.length ? `Gapped up: ${p.signals.gap_up.slice(0, 6).join(", ")}. ` : ""}
                {p.signals.gap_down?.length ? `Gapped down: ${p.signals.gap_down.slice(0, 6).join(", ")}.` : ""}
              </p>
            )}
          </div>
        </SectionCard>

        {/* sectors */}
        <SectionCard title="Sector rotation (today)" index={2}>
          <div className="grid grid-cols-2 gap-4 p-4">
            <SectorBars title="Leading" rows={data.sectors?.leaders ?? []} />
            <SectorBars title="Lagging" rows={data.sectors?.laggards ?? []} />
          </div>
        </SectionCard>

        {/* scanner */}
        <SectionCard
          title="What the scanner sees"
          index={3}
          actions={
            <button className="text-[11px] text-accent hover:underline" onClick={() => nav("/")}>
              open Trading Ideas
            </button>
          }
        >
          {data.scanner?.available ? (
            <div className="flex flex-col gap-3 p-4">
              <div className="flex items-center gap-3 text-xs">
                <span className="tabular-nums">
                  <b className="text-fg">{data.scanner.live}</b> live ideas
                </span>
                <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                  <div
                    className="bg-pos"
                    style={{ width: `${((data.scanner.long ?? 0) / Math.max(data.scanner.live ?? 1, 1)) * 100}%` }}
                  />
                  <div
                    className="bg-neg"
                    style={{ width: `${((data.scanner.short ?? 0) / Math.max(data.scanner.live ?? 1, 1)) * 100}%` }}
                  />
                </div>
                <span className="tabular-nums text-fg-faint">
                  {data.scanner.long}L / {data.scanner.short}S
                </span>
              </div>
              {data.scanner.top_sectors && data.scanner.top_sectors.length > 0 && (
                <p className="text-[11px] text-fg-muted">
                  Concentrated in{" "}
                  {data.scanner.top_sectors.map(([s, n]) => `${s} (${n})`).join(", ")}.
                </p>
              )}
              <div className="flex flex-col gap-1">
                {(data.scanner.top_ideas ?? []).slice(0, 5).map((it) => (
                  <IdeaLine key={it.symbol + it.direction} it={it} />
                ))}
              </div>
            </div>
          ) : (
            <p className="p-4 text-sm text-fg-faint">Scanner feed unavailable.</p>
          )}
        </SectionCard>

        {/* your book */}
        <SectionCard
          title="Your paper book"
          index={4}
          actions={
            <button className="text-[11px] text-accent hover:underline" onClick={() => nav("/paper")}>
              open Paper Trading
            </button>
          }
        >
          {data.book?.available ? (
            <div className="flex flex-col gap-3 p-4">
              <div className="grid grid-cols-3 gap-3">
                <Mini label="Net worth" value={inr(data.book.net_worth ?? 0)} />
                <Mini
                  label="Total P&L"
                  value={`${sgn(data.book.total_pnl_pct)}%`}
                  tone={data.book.total_pnl_pct}
                />
                <Mini
                  label="Day P&L"
                  value={inr(data.book.day_pnl ?? 0)}
                  tone={data.book.day_pnl}
                />
              </div>
              {(data.book.deployed_baskets ?? []).length > 0 && (
                <div className="text-[11px]">
                  <p className="font-semibold uppercase tracking-wide text-fg-faint">Deployed baskets</p>
                  {data.book.deployed_baskets!.map((b) => (
                    <button
                      key={b.id}
                      onClick={() => nav(`/baskets/${b.id}`)}
                      className="mt-0.5 flex w-full items-center justify-between hover:underline"
                    >
                      <span className="text-fg-muted">{b.name}</span>
                      <span className="tabular-nums">
                        <span className={cn((b.return_pct ?? 0) < 0 ? "text-neg" : "text-pos")}>
                          {sgn(b.return_pct)}%
                        </span>
                        {b.rebalance_due && (
                          <span className="ml-1.5 rounded bg-amber-400/10 px-1 text-[9px] font-semibold text-amber-500">
                            rebalance due
                          </span>
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {(data.book.movers ?? []).length > 0 && (
                <div className="text-[11px]">
                  <p className="font-semibold uppercase tracking-wide text-fg-faint">Biggest movers held</p>
                  {data.book.movers!.map((m) => (
                    <div key={m.symbol} className="mt-0.5 flex justify-between">
                      <span className="text-fg-muted">{m.symbol}</span>
                      <span
                        className={cn("tabular-nums", (m.day_change_pct ?? 0) < 0 ? "text-neg" : "text-pos")}
                      >
                        {sgn(m.day_change_pct)}% today
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {(data.book.alerts ?? []).length > 0 && (
                <ul className="space-y-0.5 rounded-md border border-amber-400/30 bg-amber-400/5 p-2 text-[11px] text-amber-600 dark:text-amber-400">
                  {data.book.alerts!.map((a, i) => (
                    <li key={i}>⚠ {a}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="p-4 text-sm text-fg-faint">Paper account unavailable.</p>
          )}
        </SectionCard>

        {/* movers */}
        <SectionCard title="Notable movers" index={5}>
          <div className="grid grid-cols-2 gap-4 p-4">
            <MoverList title="Top gainers" rows={data.movers?.gainers ?? []} pos />
            <MoverList title="Top losers" rows={data.movers?.losers ?? []} />
          </div>
        </SectionCard>

        {/* seasonality */}
        {data.seasonality?.month && (
          <SectionCard
            title="Seasonality context"
            index={6}
            actions={
              <button className="text-[11px] text-accent hover:underline" onClick={() => nav("/seasonality")}>
                open Sector Seasonality
              </button>
            }
          >
            <div className="p-4 text-[12px] text-fg-muted">
              <p>
                <b className="text-fg">{data.seasonality.month}</b>
                {data.seasonality.anchor ? ` · ${data.seasonality.anchor}` : ""}.
              </p>
              <p className="mt-1">
                Historically stronger:{" "}
                <span className="text-pos">
                  {(data.seasonality.historical_long_tilt ?? []).join(", ") || "—"}
                </span>{" "}
                · weaker:{" "}
                <span className="text-neg">
                  {(data.seasonality.historical_short_tilt ?? []).join(", ") || "—"}
                </span>
                .
              </p>
              <p className="mt-1 text-[11px] text-fg-faint">{data.seasonality.caveat}</p>
            </div>
          </SectionCard>
        )}
      </div>
    </>
  );
}

function renderBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-fg">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function Mini({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: number | null;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "tabular-nums text-sm font-semibold",
          tone == null ? "text-fg" : tone < 0 ? "text-neg" : "text-pos",
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[10px] text-fg-faint">{sub}</span>}
    </div>
  );
}

function SectorBars({ title, rows }: { title: string; rows: SectorRow[] }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.avg_change_pct)));
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">{title}</p>
      <div className="mt-1 flex flex-col gap-1.5">
        {rows.map((r) => (
          <div key={r.sector} className="text-[11px]">
            <div className="flex justify-between">
              <span className="text-fg-muted">{short(r.sector)}</span>
              <span
                className={cn("tabular-nums", r.avg_change_pct < 0 ? "text-neg" : "text-pos")}
              >
                {sgn(r.avg_change_pct)}%
              </span>
            </div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-elevated">
              <div
                className={r.avg_change_pct < 0 ? "bg-neg" : "bg-pos"}
                style={{ width: `${(Math.abs(r.avg_change_pct) / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IdeaLine({ it }: { it: ScannerIdea }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span
        className={cn("w-9 font-bold", it.direction === "LONG" ? "text-pos" : "text-neg")}
      >
        {it.direction === "LONG" ? "BUY" : "SELL"}
      </span>
      <span className="w-20 truncate font-medium text-fg">{it.symbol}</span>
      <span
        className={cn(
          "rounded px-1 text-[9px] font-semibold",
          it.grade === "A"
            ? "bg-pos/10 text-pos"
            : it.grade === "B"
              ? "bg-amber-400/10 text-amber-500"
              : "bg-elevated text-fg-muted",
        )}
      >
        {it.grade ?? "C"} {num(it.confidence, 0)}
      </span>
      <span className="truncate text-fg-faint">{it.setup}</span>
      {it.rr != null && <span className="ml-auto tabular-nums text-fg-faint">{num(it.rr, 1)}R</span>}
    </div>
  );
}

function MoverList({ title, rows, pos }: { title: string; rows: MoverRow[]; pos?: boolean }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">{title}</p>
      <div className="mt-1 flex flex-col gap-0.5">
        {rows.map((r) => (
          <div key={r.symbol} className="flex justify-between text-[11px]">
            <span className="text-fg-muted">{short(r.symbol)}</span>
            <span className={cn("tabular-nums", pos ? "text-pos" : "text-neg")}>
              {sgn(r.change_pct, 2)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
