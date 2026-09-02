import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ArbBacktest, ArbCategory } from "@/api/arbitrage";
import { DataTable, type Column } from "@/components/DataTable";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useArbBacktests,
  useArbLibrary,
  useArbPortfolio,
  useArbScanner,
  useLatestDiscovery,
  useRunArbBacktest,
  useRunPairDiscovery,
} from "@/hooks/useArbitrage";
import { inr, inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const CAT_BADGE: Record<ArbCategory, string> = {
  TRUE_ARBITRAGE: "bg-pos/15 text-pos",
  STATISTICAL_ARBITRAGE: "bg-sky-500/15 text-sky-400",
  RELATIVE_VALUE: "bg-violet-500/15 text-violet-400",
  BASIS_ARBITRAGE: "bg-amber-500/15 text-amber-500",
  LATENCY_DEPENDENT: "bg-rose-500/15 text-rose-400",
  RESEARCH_ONLY: "bg-fg-faint/15 text-fg-faint",
};

function Shell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={title} subtitle={subtitle} />
      {children}
    </div>
  );
}

function Phase({ n, what }: { n: number; what: string }) {
  return (
    <Card>
      <CardContent className="py-8 text-center text-sm text-fg-muted">
        <p className="font-medium text-fg">Planned — Phase {n}</p>
        <p className="mx-auto mt-1 max-w-lg text-xs text-fg-faint">{what}</p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- Library

export function ArbitrageLibraryPage() {
  const { data, isLoading } = useArbLibrary();
  return (
    <Shell
      title="Arbitrage Lab — Strategy Library"
      subtitle="A separate research subsystem. Every opportunity is judged on NET expected edge — not raw price deviation."
    >
      {isLoading || !data ? (
        <p className="text-sm text-fg-faint">Loading…</p>
      ) : (
        <>
          <Card>
            <CardContent className="p-3 text-xs leading-relaxed text-fg-muted">
              <span className="font-semibold text-fg">Net edge rule.</span> {data.net_edge_rule}
            </CardContent>
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            {data.strategies.map((s) => (
              <Card key={s.slug}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between gap-2 text-base">
                    <span>{s.name}</span>
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold", CAT_BADGE[s.category])}>
                      {s.category.replace(/_/g, " ")}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2 text-xs text-fg-muted">
                  <p>{s.description}</p>
                  <p className="text-fg-faint">{data.categories[s.category]}</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge>{s.legs}</Badge>
                    <Badge variant="info">latency: {s.latency_sensitivity}</Badge>
                    <Badge>{s.infra_note}</Badge>
                    <Badge>min net edge {s.min_net_edge_bps_default} bps</Badge>
                  </div>
                  <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-300 light:text-amber-700">
                    {s.warning}
                  </p>
                  <Link
                    to={`/arbitrage/backtest?slug=${s.slug}`}
                    className="text-accent hover:underline"
                  >
                    Backtest this strategy →
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Roadmap</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-fg-muted">
              <p>
                <span className="text-pos">Implemented:</span> {data.roadmap.implemented.join(", ")}
              </p>
              <p className="mt-1">
                <span className="text-fg-faint">Planned:</span> {data.roadmap.planned.join(", ")}
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- Backtesting

export function ArbBacktestPage() {
  const { data: lib } = useArbLibrary();
  const run = useRunArbBacktest();
  const { data: history } = useArbBacktests();

  const params = new URLSearchParams(window.location.search);
  const [slug, setSlug] = useState(params.get("slug") ?? "pairs-arb");
  const [a, setA] = useState<string[]>(["NSE:HDFCBANK"]);
  const [b, setB] = useState<string[]>(["NSE:ICICIBANK"]);
  const [timeframe, setTimeframe] = useState("1d");
  const [preset, setPreset] = useState("balanced");
  const [syncMode, setSyncMode] = useState("REJECT_STALE_DATA");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const strat = lib?.strategies.find((s) => s.slug === slug);
  const result = run.data;

  return (
    <Shell
      title="Arbitrage Lab — Backtesting"
      subtitle="Dedicated multi-leg engine: independent per-leg fills & costs, data synchronisation, financing, partial fills. Not the directional backtester."
    >
      <Card>
        <CardHeader>
          <CardTitle>New arbitrage backtest</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label>Strategy</Label>
            <select
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {lib?.strategies.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Preset</Label>
            <select
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {Object.keys(strat?.presets ?? { balanced: 1 }).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{strat?.category === "BASIS_ARBITRAGE" ? (slug === "calendar-spread" ? "Leg A — near future" : "Leg A — spot / index proxy") : "Leg A"}</Label>
            <InstrumentSearch value={a} onChange={setA} multiple={false} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{strat?.category === "BASIS_ARBITRAGE" ? (slug === "calendar-spread" ? "Leg B — far future" : "Leg B — near future") : "Leg B"}</Label>
            <InstrumentSearch value={b} onChange={setB} multiple={false} />
          </div>
          {strat?.category === "BASIS_ARBITRAGE" && (
            <p className="lg:col-span-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-300 light:text-amber-700">
              Use F&amp;O tradingsymbols for the future leg(s). Expiry is derived from the instrument
              master. {strat.infra_note}
            </p>
          )}
          <div className="flex flex-col gap-1.5">
            <Label>Timeframe</Label>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {(strat?.supported_timeframes ?? ["1d"]).map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Data sync mode</Label>
            <select
              value={syncMode}
              onChange={(e) => setSyncMode(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {["REJECT_STALE_DATA", "STRICT_SYNC", "FORWARD_FILL_LIMITED", "LAST_VALID_PRICE_WITH_MAX_AGE"].map(
                (m) => (
                  <option key={m}>{m}</option>
                ),
              )}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Start (optional)</Label>
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>End (optional)</Label>
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="lg:col-span-2">
            <Button
              disabled={run.isPending || !a[0] || !b[0]}
              onClick={() =>
                run.mutate({
                  slug,
                  symbol_a: a[0],
                  symbol_b: b[0],
                  timeframe,
                  preset,
                  sync_mode: syncMode,
                  start: start || undefined,
                  end: end || undefined,
                })
              }
            >
              {run.isPending ? "Running…" : "Run arbitrage backtest"}
            </Button>
            {run.isError && <span className="ml-3 text-xs text-neg">{(run.error as Error).message}</span>}
          </div>
        </CardContent>
      </Card>

      {result && <ArbResultView r={result} />}

      {history && history.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Cached runs</CardTitle>
          </CardHeader>
          <CardContent className="text-xs">
            <table className="w-full text-left">
              <thead className="text-fg-faint">
                <tr>
                  <th className="py-1 pr-3">Strategy · legs</th>
                  <th className="py-1 pr-3">Net P&L</th>
                  <th className="py-1 pr-3">Sharpe</th>
                  <th className="py-1 pr-3">Edge capture</th>
                  <th className="py-1">Quality</th>
                </tr>
              </thead>
              <tbody className="text-fg-muted">
                {history.map((h, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1 pr-3">
                      {h.strategy_name} · {h.legs.join(" / ")}
                    </td>
                    <td className={cn("py-1 pr-3 tabular-nums", (h.metrics.net_pnl ?? 0) < 0 && "text-neg")}>
                      {inrCompact(h.metrics.net_pnl)}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">{num(h.metrics.sharpe_ratio, 2)}</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {num((h.metrics.edge_capture_rate ?? 0) * 100, 0)}%
                    </td>
                    <td className="py-1 tabular-nums">{num(h.metrics.arbitrage_quality_score, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </Shell>
  );
}

function K({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-md border border-line bg-elevated px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div className={cn("font-mono text-sm tabular-nums", tone === "pos" && "text-pos", tone === "neg" && "text-neg")}>
        {value}
      </div>
    </div>
  );
}

function ArbResultView({ r }: { r: ArbBacktest }) {
  const m = r.metrics;
  const eq = useMemo(
    () => r.equity_curve.map(([t, v]) => ({ t: t.slice(0, 10), v: Math.round(v) })),
    [r.equity_curve],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {r.strategy_name} — {r.legs.join(" / ")}
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold", CAT_BADGE[r.category])}>
            {r.category.replace(/_/g, " ")}
          </span>
          <span className="text-xs font-normal text-fg-faint">
            {r.preset} · {r.timeframe} · {r.start}→{r.end} · sync {r.sync_mode}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300 light:text-amber-700">
          {r.warning} · {r.infra_note}
        </p>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          <K label="Net P&L" value={inr(m.net_pnl)} tone={(m.net_pnl ?? 0) >= 0 ? "pos" : "neg"} />
          <K label="Return / capital" value={`${num(m.return_on_capital_pct)}%`} />
          <K label="Sharpe" value={num(m.sharpe_ratio, 2)} />
          <K label="Max DD" value={`${num(m.max_drawdown_pct)}%`} tone="neg" />
          <K label="Opps seen / done" value={`${m.opportunities_seen} / ${m.opportunities_executed}`} />
          <K label="Win rate" value={`${num(m.win_rate_pct, 1)}%`} />
          <K label="Avg net edge" value={inr(m.avg_net_edge)} />
          <K
            label="Edge capture"
            value={`${num((m.edge_capture_rate ?? 0) * 100, 0)}%`}
            tone={(m.edge_capture_rate ?? 0) >= 0.5 ? "pos" : "neg"}
          />
          <K label="Convergence" value={`${num((m.convergence_rate ?? 0) * 100, 0)}%`} />
          <K label="Partial fills" value={`${num((m.partial_fill_rate ?? 0) * 100, 0)}%`} />
          <K label="Leg imbalance" value={`${num((m.leg_imbalance_rate ?? 0) * 100, 0)}%`} />
          <K
            label="Arb quality"
            value={`${num(m.arbitrage_quality_score, 0)}/100`}
            tone={(m.arbitrage_quality_score ?? 0) >= 60 ? "pos" : "neg"}
          />
        </div>

        <div className="flex flex-wrap gap-4 text-xs text-fg-muted">
          <span>
            Data quality: <span className="tabular-nums">{r.data_quality.data_quality_score}</span> ·
            skew {r.data_quality.max_data_skew_seconds}s · stale {r.data_quality.stale_events} ·
            missing {r.data_quality.missing_events} · used {r.data_quality.used_points}/
            {r.data_quality.total_timeline}
          </span>
          {r.diagnostics.rejected && Object.keys(r.diagnostics.rejected).length > 0 && (
            <span>
              rejected:{" "}
              {Object.entries(r.diagnostics.rejected)
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
            </span>
          )}
        </div>

        {eq.length > 1 && (
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <AreaChart data={eq} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                <defs>
                  <linearGradient id="arbeq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={48} />
                <YAxis tick={{ fontSize: 10 }} width={64} tickFormatter={(v) => inrCompact(v as number)} domain={["auto", "auto"]} />
                <Tooltip
                  formatter={(v) => inr(v as number)}
                  contentStyle={{ background: "var(--color-surface)", border: "1px solid var(--color-line-strong)", fontSize: 12 }}
                />
                <Area type="monotone" dataKey="v" stroke="var(--color-accent)" strokeWidth={1.5} fill="url(#arbeq)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {r.trades.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-fg-faint">
                <tr>
                  <th className="py-1 pr-3">Entry → Exit</th>
                  <th className="py-1 pr-3">Dir</th>
                  <th className="py-1 pr-3">Bars</th>
                  <th className="py-1 pr-3">Gross</th>
                  <th className="py-1 pr-3">Costs</th>
                  <th className="py-1 pr-3">Net</th>
                  <th className="py-1 pr-3">Edge capt.</th>
                  <th className="py-1 pr-3">Legs</th>
                  <th className="py-1">Exit</th>
                </tr>
              </thead>
              <tbody className="text-fg-muted">
                {r.trades.slice(0, 60).map((t, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1 pr-3">
                      {t.entry_ts.slice(0, 10)} → {t.exit_ts.slice(0, 10)}
                    </td>
                    <td className="py-1 pr-3">{t.direction}</td>
                    <td className="py-1 pr-3 tabular-nums">{t.bars_held}</td>
                    <td className="py-1 pr-3 tabular-nums">{inrCompact(t.gross_pnl)}</td>
                    <td className="py-1 pr-3 tabular-nums">{inrCompact(t.total_costs)}</td>
                    <td className={cn("py-1 pr-3 tabular-nums", t.net_pnl < 0 ? "text-neg" : "text-pos")}>
                      {inrCompact(t.net_pnl)}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">{num(t.edge_capture_rate * 100, 0)}%</td>
                    <td className="py-1 pr-3">
                      {t.legs.map((l) => `${l.side} ${l.filled_qty}/${l.target_qty} ${l.instrument}`).join(" · ")}
                      {t.partial_fill && <span className="ml-1 text-amber-500">partial</span>}
                    </td>
                    <td className="py-1">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- Pair Discovery

export function ArbPairDiscoveryPage() {
  const disc = useRunPairDiscovery();
  const { data: latest } = useLatestDiscovery();
  const [symbols, setSymbols] = useState<string[]>([
    "NSE:HDFCBANK",
    "NSE:ICICIBANK",
    "NSE:AXISBANK",
    "NSE:KOTAKBANK",
    "NSE:SBIN",
    "NSE:INFY",
    "NSE:TCS",
    "NSE:WIPRO",
  ]);
  const [days, setDays] = useState(500);
  const data = disc.data ?? (latest?.available ? latest : undefined);

  const columns: Column<NonNullable<typeof data>["pairs"][number]>[] = [
    { key: "pair", header: "Pair", sortValue: (r) => `${r.symbol_a}/${r.symbol_b}`, cell: (r) => `${r.symbol_a} / ${r.symbol_b}` },
    { key: "score", header: "Score", align: "right", sortValue: (r) => r.discovery_score, cell: (r) => <span className="font-mono">{num(r.discovery_score, 0)}</span> },
    { key: "corr", header: "Corr", align: "right", sortValue: (r) => r.return_correlation, cell: (r) => num(r.return_correlation, 2) },
    { key: "adf", header: "ADF t", align: "right", sortValue: (r) => r.adf_tstat ?? 99, cell: (r) => (r.adf_tstat == null ? "—" : num(r.adf_tstat, 2)) },
    { key: "coint", header: "Coint", align: "center", sortValue: (r) => (r.cointegrated ? 1 : 0), cell: (r) => (r.cointegrated ? <span className="text-pos">yes</span> : <span className="text-fg-faint">no</span>) },
    { key: "hl", header: "Half-life", align: "right", sortValue: (r) => r.half_life_bars ?? 999, cell: (r) => (r.half_life_bars == null ? "—" : num(r.half_life_bars, 0)) },
    { key: "stab", header: "Stability", align: "right", sortValue: (r) => r.spread_stability, cell: (r) => num(r.spread_stability, 2) },
    { key: "liq", header: "Liquidity", align: "right", sortValue: (r) => r.liquidity_score, cell: (r) => num(r.liquidity_score, 0) },
    {
      key: "trade",
      header: "Tradeable",
      align: "center",
      sortValue: (r) => (r.tradeable ? 1 : 0),
      cell: (r) =>
        r.tradeable ? (
          <Link to={`/arbitrage/backtest?slug=cointegration-arb`} className="text-pos hover:underline">
            yes →
          </Link>
        ) : (
          <span className="text-fg-faint">no</span>
        ),
    },
  ];

  return (
    <Shell
      title="Arbitrage Lab — Pair Discovery"
      subtitle="Scan a universe for cointegrated, mean-reverting, liquid pairs. A pair is only 'tradeable' when it passes every gate."
    >
      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <Label>Universe</Label>
          <InstrumentSearch value={symbols} onChange={setSymbols} multiple />
          <div className="flex items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>Lookback (days)</Label>
              <Input type="number" value={days} min={120} step={30} onChange={(e) => setDays(Number(e.target.value) || 500)} className="w-32" />
            </div>
            <Button disabled={disc.isPending || symbols.length < 2} onClick={() => disc.mutate({ symbols, days })}>
              {disc.isPending ? "Scanning…" : "Discover pairs"}
            </Button>
            {disc.isError && <span className="text-xs text-neg">{(disc.error as Error).message}</span>}
          </div>
        </CardContent>
      </Card>

      {data && (
        <Card>
          <CardHeader>
            <CardTitle>
              {data.pairs.length} candidates · {data.tradeable_count} tradeable ·{" "}
              {data.universe_size} names · {data.days}d · generated {new Date(data.generated_at).toLocaleString()}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <DataTable columns={columns} rows={data.pairs} rowKey={(r) => `${r.symbol_a}/${r.symbol_b}`} initialSort={{ key: "score", dir: "desc" }} />
          </CardContent>
        </Card>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- Portfolio

export function ArbPortfolioPage() {
  const { data, isLoading } = useArbPortfolio();
  return (
    <Shell
      title="Arbitrage Lab — Portfolio"
      subtitle="Aggregate of arbitrage backtest runs. Kept entirely separate from the Quant Strategy Leaderboard."
    >
      {isLoading || !data ? (
        <p className="text-sm text-fg-faint">Loading…</p>
      ) : data.run_count === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-fg-faint">
            No arbitrage backtests run yet. Start on the Backtesting tab.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <K label="Runs" value={String(data.run_count)} />
            <K
              label="Combined net P&L"
              value={inr(data.combined_net_pnl)}
              tone={data.combined_net_pnl >= 0 ? "pos" : "neg"}
            />
          </div>
          <Card>
            <CardContent className="overflow-x-auto p-0">
              <table className="w-full text-left text-xs">
                <thead className="text-fg-faint">
                  <tr>
                    <th className="p-2">Strategy · legs</th>
                    <th className="p-2">Category</th>
                    <th className="p-2 text-right">Opps</th>
                    <th className="p-2 text-right">Net P&L</th>
                    <th className="p-2 text-right">RoC %</th>
                    <th className="p-2 text-right">Sharpe</th>
                    <th className="p-2 text-right">Max DD</th>
                    <th className="p-2 text-right">Edge capt.</th>
                    <th className="p-2 text-right">Data Q</th>
                    <th className="p-2 text-right">Arb quality</th>
                  </tr>
                </thead>
                <tbody className="text-fg-muted">
                  {data.runs.map((r, i) => (
                    <tr key={i} className="border-t border-line">
                      <td className="p-2">
                        {r.strategy_name}
                        <div className="text-[10px] text-fg-faint">{r.legs.join(" / ")} · {r.preset}</div>
                      </td>
                      <td className="p-2">{r.category.replace(/_/g, " ")}</td>
                      <td className="p-2 text-right tabular-nums">
                        {r.executed}/{r.opportunities}
                      </td>
                      <td className={cn("p-2 text-right tabular-nums", (r.net_pnl ?? 0) < 0 && "text-neg")}>
                        {inrCompact(r.net_pnl)}
                      </td>
                      <td className="p-2 text-right tabular-nums">{num(r.return_on_capital_pct)}</td>
                      <td className="p-2 text-right tabular-nums">{num(r.sharpe_ratio, 2)}</td>
                      <td className="p-2 text-right tabular-nums">{num(r.max_drawdown_pct)}</td>
                      <td className="p-2 text-right tabular-nums">{num((r.edge_capture_rate ?? 0) * 100, 0)}%</td>
                      <td className="p-2 text-right tabular-nums">{num(r.data_quality_score, 0)}</td>
                      <td className="p-2 text-right tabular-nums">{num(r.arbitrage_quality_score, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
          <p className="text-xs text-fg-faint">{data.note}</p>
        </>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- Scanner (Phase 1 stub w/ real endpoint)

export function ArbScannerPage() {
  const { data } = useArbScanner();
  return (
    <Shell
      title="Arbitrage Lab — Opportunity Scanner"
      subtitle="Real-time net-edge screening across strategies. Marks EXECUTABLE only when data is fresh, net edge is positive, liquidity and risk limits pass."
    >
      <Card>
        <CardContent className="py-8 text-center text-sm text-fg-muted">
          {data?.reason ??
            "The live scanner needs a synchronised real-time quote feed for every leg — wired in a later phase."}
          <div className="mt-3 flex flex-wrap justify-center gap-1.5 text-[10px]">
            {(data?.statuses ?? []).map((s) => (
              <Badge key={s}>{s}</Badge>
            ))}
          </div>
        </CardContent>
      </Card>
    </Shell>
  );
}

// ---------------------------------------------------------------- Phase-2+ shells

export function ArbPaperPage() {
  return (
    <Shell
      title="Arbitrage Lab — Paper Trading"
      subtitle="Dedicated multi-leg paper engine: independent per-leg fills, hedge-state tracking, execution-quality scoring — separate from directional paper trading."
    >
      <Phase
        n={1}
        what="Multi-leg paper execution (FULLY_HEDGED / PARTIALLY_HEDGED / UNHEDGED / LEG_IMBALANCE states, realistic bid/ask + latency + partial fills, EXECUTION_QUALITY_SCORE) and the paper account dashboard with start/pause/close-all controls."
      />
    </Shell>
  );
}

export function ArbLiveMonitorPage() {
  return (
    <Shell title="Arbitrage Lab — Live Monitor" subtitle="Open structures, per-leg fill %, unhedged exposure, time-unhedged, convergence status.">
      <Phase n={1} what="Live position monitor for the arbitrage paper/live engine — renders once the paper engine lands." />
    </Shell>
  );
}

export function ArbAnalyticsPage() {
  return (
    <Shell
      title="Arbitrage Lab — Analytics"
      subtitle="Backtest-vs-paper comparison, edge-capture rate, slippage distribution, execution-failure analysis."
    >
      <Phase
        n={2}
        what="BACKTEST vs LIVE PAPER comparison (net return, win rate, Sharpe, slippage, opportunity frequency, EDGE_CAPTURE_RATE = realised / theoretical edge) plus slippage & execution-failure distributions. Needs the paper engine's live track record."
      />
    </Shell>
  );
}
