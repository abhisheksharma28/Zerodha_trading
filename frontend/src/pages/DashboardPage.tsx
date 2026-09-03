import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Bot, FlaskConical, Radar, Wallet } from "lucide-react";

import type { ScanRecommendation } from "@/api/marketScanner";
import { DataTable, type Column } from "@/components/DataTable";
import { ModeBadge } from "@/components/ModeBadge";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useBacktests } from "@/hooks/useBacktests";
import { useDeployments } from "@/hooks/useDeployments";
import { useBacktestCatalog } from "@/hooks/useLeaderboard";
import { useScanRecommendations, useScannerStatus } from "@/hooks/useMarketScanner";
import {
  useAddIdeaToPaper,
  usePaperAlgo,
  usePaperHoldings,
  usePaperPositions,
  usePaperStrategyRuns,
  usePaperSummary,
} from "@/hooks/usePaperAccount";
import { useStrategies } from "@/hooks/useStrategies";
import { inr, num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Backtest } from "@/types/api";

const TIP = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-line-strong)",
  color: "var(--color-fg)",
  fontSize: 12,
};

const SAMPLE_ALLOCATION = [
  { name: "Equity", value: 52, color: "var(--color-accent)" },
  { name: "Options", value: 23, color: "#22b8cf" },
  { name: "Futures", value: 18, color: "#ffa94d" },
  { name: "Cash", value: 7, color: "var(--color-line-strong)" },
];
const ALLOC_COLORS: Record<string, string> = {
  Equity: "var(--color-accent)",
  Options: "#22b8cf",
  Futures: "#ffa94d",
  Cash: "var(--color-line-strong)",
};

const GRADE_RANK: Record<string, number> = { A: 3, B: 2, C: 1 };
const pnlTone = (v: number | null | undefined) =>
  (v ?? 0) > 0 ? "pos" : (v ?? 0) < 0 ? "neg" : "muted";

function IdeaRow({
  rec,
  taken,
  onAdd,
  adding,
}: {
  rec: ScanRecommendation;
  taken: boolean;
  onAdd: () => void;
  adding: boolean;
}) {
  const style =
    rec.trade_style === "OPTION"
      ? "Options"
      : rec.trade_style === "EQUITY_INTRADAY"
        ? "Intraday"
        : "Delivery";
  return (
    <div className="flex items-center gap-3 border-b border-line/60 px-3 py-2 text-xs last:border-0">
      <span className={cn("w-10 shrink-0 font-bold", rec.direction === "LONG" ? "text-pos" : "text-neg")}>
        {rec.direction === "LONG" ? "BUY" : "SELL"}
      </span>
      <Link
        to={`/stocks/${rec.exchange}/${rec.tradingsymbol}`}
        className="w-24 shrink-0 truncate font-medium text-fg hover:text-accent"
      >
        {rec.tradingsymbol}
      </Link>
      <span className="w-16 shrink-0 text-fg-faint">{style}</span>
      <span
        className={cn(
          "w-9 shrink-0 rounded border px-1 text-center text-[10px] font-semibold",
          rec.grade === "A"
            ? "border-pos/40 bg-pos/10 text-pos"
            : rec.grade === "B"
              ? "border-amber-400/40 bg-amber-400/10 text-amber-500"
              : "border-line text-fg-muted",
        )}
      >
        {rec.grade ?? "C"} {num(rec.confidence, 0)}
      </span>
      <span className="hidden flex-1 items-center gap-2 tabular-nums text-fg-muted sm:flex">
        <span>e {num(rec.entry, 1)}</span>
        <span className="text-neg">sl {num(rec.stop_loss, 1)}</span>
        <span className="text-pos">t {num(rec.target_1, 1)}</span>
        {rec.rr != null && <span>· {num(rec.rr, 1)}R</span>}
      </span>
      <button
        type="button"
        disabled={taken || adding}
        onClick={onAdd}
        className={cn(
          "ml-auto shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-semibold",
          taken
            ? "cursor-default border-pos/40 bg-pos/10 text-pos"
            : "border-accent/50 text-accent hover:bg-accent-soft disabled:opacity-60",
        )}
      >
        {taken ? "✓ in paper" : adding ? "…" : "＋ paper"}
      </button>
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const strategies = useStrategies();
  const deployments = useDeployments();
  const backtests = useBacktests();
  const { data: catalog } = useBacktestCatalog();
  const totalBacktests = catalog?.meta.total_backtests ?? backtests.data?.length ?? 0;

  const { data: sm } = usePaperSummary(15_000);
  const { data: positions = [] } = usePaperPositions(15_000);
  const { data: holdings = [] } = usePaperHoldings(20_000);
  const { data: algo } = usePaperAlgo(15_000);
  const { data: stratRuns = [] } = usePaperStrategyRuns(20_000);
  const { data: recs } = useScanRecommendations(20_000);
  const { data: scan } = useScannerStatus(30_000);
  const addIdea = useAddIdeaToPaper();

  const running = deployments.data?.filter((d) => d.status === "running") ?? [];
  const live = running.filter((d) => d.mode === "live");
  const activeStrats = stratRuns.filter((r) => r.status === "ACTIVE");

  const dayPnl =
    (sm?.pnl.positions_unrealized ?? 0) + (sm?.pnl.holdings_day ?? 0) + (sm?.pnl.booked ?? 0);

  // real allocation from the paper account (falls back to a labelled sample)
  const alloc = useMemo(() => {
    const optionVal = positions
      .filter((p) => p.asset_class === "OPT")
      .reduce((s, p) => s + (p.value ?? 0), 0);
    const futVal = positions
      .filter((p) => p.asset_class === "FUT")
      .reduce((s, p) => s + (p.value ?? 0), 0);
    const eqPosVal = positions
      .filter((p) => p.asset_class === "EQUITY")
      .reduce((s, p) => s + (p.value ?? 0), 0);
    const equityVal = holdings.reduce((s, h) => s + h.current_value, 0) + eqPosVal;
    const cash = sm?.funds.available_margin ?? 0;
    const rows = [
      { name: "Equity", value: equityVal },
      { name: "Options", value: optionVal },
      { name: "Futures", value: futVal },
      { name: "Cash", value: cash },
    ].filter((r) => r.value > 0.5);
    const total = rows.reduce((s, r) => s + r.value, 0);
    if (total <= 0 || rows.length === 1) return null;
    return rows.map((r) => ({ ...r, pct: (r.value / total) * 100, color: ALLOC_COLORS[r.name] }));
  }, [positions, holdings, sm?.funds.available_margin]);

  // the ideas the auto-trader would take next, given the current rules
  const topIdeas = useMemo(() => {
    const minG = GRADE_RANK[algo?.config.min_grade ?? "B"] ?? 2;
    const allow = (r: ScanRecommendation) =>
      ({
        EQUITY_DELIVERY: algo?.config.allow_delivery ?? true,
        EQUITY_INTRADAY: algo?.config.allow_intraday ?? true,
        OPTION: algo?.config.allow_options ?? true,
      })[r.trade_style] ?? true;
    return (recs?.live ?? [])
      .filter((r) => GRADE_RANK[r.grade ?? "C"] >= minG && allow(r))
      .sort(
        (a, b) =>
          GRADE_RANK[b.grade ?? "C"] - GRADE_RANK[a.grade ?? "C"] ||
          (b.confidence ?? 0) - (a.confidence ?? 0),
      )
      .slice(0, 5);
  }, [recs?.live, algo?.config]);
  const takenSet = useMemo(() => new Set(recs?.paper_taken ?? []), [recs?.paper_taken]);

  const completed = (backtests.data ?? []).filter((b) => b.equity_curve && b.equity_curve.length > 1);
  const latest = completed.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))[0];
  const equity = latest?.equity_curve?.map(([ts, v], i) => ({ i, ts, v: Number(v) })) ?? [];
  const recent = (backtests.data ?? [])
    .slice()
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    .slice(0, 6);

  const backtestCols: Column<Backtest>[] = [
    {
      key: "sym",
      header: "Universe",
      cell: (b) => <span className="font-medium text-fg">{b.instrument_universe.join(", ")}</span>,
      sortValue: (b) => b.instrument_universe.join(", "),
    },
    { key: "tf", header: "TF", cell: (b) => b.timeframe, sortValue: (b) => b.timeframe },
    {
      key: "ret",
      header: "Return",
      align: "right",
      cell: (b) => {
        const r = b.metrics?.total_return_pct;
        if (r == null) return <span className="text-fg-faint">–</span>;
        return <span className={r < 0 ? "text-neg" : "text-pos"}>{r.toFixed(2)}%</span>;
      },
      sortValue: (b) => b.metrics?.total_return_pct ?? null,
    },
    {
      key: "status",
      header: "Status",
      align: "right",
      cell: (b) => (
        <Badge
          variant={
            b.status === "completed"
              ? "success"
              : b.status === "failed"
                ? "destructive"
                : b.status === "running"
                  ? "info"
                  : "default"
          }
        >
          {b.status}
        </Badge>
      ),
      sortValue: (b) => b.status,
    },
  ];

  const algoOn = algo?.config.enabled ?? false;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Dashboard"
        subtitle="Your paper portfolio, the auto-trader, and what the engine is watching right now."
      />

      {live.length > 0 && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="flex items-center justify-between py-3">
            <p className="text-sm font-medium text-neg">
              {live.length} deployment{live.length > 1 ? "s" : ""} trading LIVE with real money.
            </p>
            <Link to="/monitoring" className="text-xs text-red-300 underline underline-offset-2">
              Go to monitoring →
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Paper net worth"
          value={inr(sm?.net_worth ?? 0)}
          delta={sm ? `${pctSigned((dayPnl / (sm.net_worth || 1)) * 100)} today · ${inr(dayPnl)}` : undefined}
          deltaTone={pnlTone(dayPnl)}
          icon={Wallet}
        />
        <StatCard
          label="Paper P&L (total)"
          value={inr(sm?.pnl.total ?? 0)}
          delta={sm ? `booked ${inr(sm.pnl.booked)}` : undefined}
          deltaTone={pnlTone(sm?.pnl.total)}
          icon={FlaskConical}
        />
        <StatCard
          label="Auto-trader"
          value={algoOn ? "ON" : "OFF"}
          valueClassName={algoOn ? "text-pos" : "text-fg-muted"}
          delta={
            algo
              ? algo.halted
                ? "halted for today"
                : `${algo.open_auto_positions}/${algo.max_open_auto} auto open · ${inr(algo.today_realized_pnl)} today`
              : undefined
          }
          deltaTone={algo?.halted ? "neg" : "muted"}
          icon={Bot}
        />
        <StatCard
          label="Live trade ideas"
          value={scan?.live_count ?? recs?.summary.live ?? 0}
          delta={
            scan?.market_phase
              ? `market ${scan.market_phase.replace("_", " ")}${
                  recs?.last_scan?.at
                    ? ` · scan ${new Date(recs.last_scan.at).toLocaleTimeString("en-IN")}`
                    : ""
                }`
              : undefined
          }
          icon={Radar}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title="Portfolio Equity Curve"
          className="lg:col-span-2"
          actions={
            latest ? (
              <Link to={`/backtests/${latest.id}`} className="text-xs text-accent hover:underline">
                {latest.instrument_universe.join(", ")} · {latest.timeframe}
              </Link>
            ) : null
          }
        >
          {equity.length === 0 ? (
            <p className="py-10 text-center text-sm text-fg-faint">
              Run a backtest to see an equity curve here.
            </p>
          ) : (
            <div className="h-56 w-full">
              <ResponsiveContainer>
                <AreaChart data={equity} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="i" stroke="var(--color-fg-faint)" fontSize={11} tickLine={false} />
                  <YAxis
                    stroke="var(--color-fg-faint)"
                    fontSize={11}
                    tickLine={false}
                    width={64}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip contentStyle={TIP} labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""} />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke="var(--color-accent)"
                    strokeWidth={2}
                    fill="url(#eqfill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="Paper allocation"
          actions={
            !alloc ? <span className="text-[10px] uppercase text-fg-faint">Sample</span> : null
          }
        >
          <div className="h-48 w-full">
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={alloc ?? SAMPLE_ALLOCATION}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={42}
                  outerRadius={68}
                  paddingAngle={2}
                  stroke="none"
                >
                  {(alloc ?? SAMPLE_ALLOCATION).map((s) => (
                    <Cell key={s.name} fill={s.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={TIP}
                  formatter={(v: number) => (alloc ? inr(v) : `${v}%`)}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-fg-muted">
            {(alloc ?? SAMPLE_ALLOCATION.map((s) => ({ ...s, pct: s.value }))).map((s) => (
              <span key={s.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.name} {num(s.pct, 0)}%
              </span>
            ))}
          </div>
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title={
            <span className="flex items-center gap-2">
              Top ideas the auto-trader could take
              {algo && (
                <Badge variant={algoOn ? "success" : "default"} className="text-[10px]">
                  {algoOn ? "auto ON" : "auto OFF"}
                </Badge>
              )}
            </span>
          }
          className="lg:col-span-2"
          actions={
            <Link to="/" className="text-xs text-accent hover:underline">
              All ideas
            </Link>
          }
          bodyClassName="p-0"
        >
          {topIdeas.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-faint">
              {recs?.available
                ? `No ideas clear the current rules (grade ≥ ${algo?.config.min_grade ?? "B"}).`
                : "Live market data unavailable — no ideas right now."}
            </p>
          ) : (
            <>
              <p className="px-3 pt-2 text-[11px] text-fg-faint">
                Filtered by the auto-trader's rules (grade ≥ {algo?.config.min_grade ?? "B"},{" "}
                {[
                  algo?.config.allow_delivery && "delivery",
                  algo?.config.allow_intraday && "intraday",
                  algo?.config.allow_options && "options",
                ]
                  .filter(Boolean)
                  .join(" / ")}
                ). {algoOn ? "It takes these automatically." : "Turn the auto-trader on in Paper Trading, or add one here."}
              </p>
              <div className="mt-1">
                {topIdeas.map((r) => (
                  <IdeaRow
                    key={r.id}
                    rec={r}
                    taken={takenSet.has(r.id)}
                    adding={addIdea.isPending && addIdea.variables?.recommendation_id === r.id}
                    onAdd={() => addIdea.mutate({ recommendation_id: r.id })}
                  />
                ))}
              </div>
            </>
          )}
        </SectionCard>

        <SectionCard title="Running in the background">
          <div className="flex flex-col gap-3 text-sm">
            <Link
              to="/paper"
              className="flex items-center justify-between rounded-md border border-line px-3 py-2 hover:bg-elevated/60"
            >
              <span className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-accent" />
                Auto-trader
              </span>
              <Badge variant={algoOn ? "success" : "default"} className="text-[10px]">
                {algo?.halted ? "halted" : algoOn ? "ON" : "OFF"}
              </Badge>
            </Link>

            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                Paper strategies ({activeStrats.length} active)
              </p>
              {stratRuns.length === 0 ? (
                <p className="text-xs text-fg-faint">
                  None deployed.{" "}
                  <Link to="/paper" className="text-accent hover:underline">
                    Deploy one →
                  </Link>
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {stratRuns.slice(0, 5).map((r) => (
                    <li
                      key={r.id}
                      className="flex items-center justify-between rounded border border-line px-2 py-1 text-xs"
                    >
                      <span className="min-w-0">
                        <span className="font-medium text-fg">{r.name}</span>
                        <span className="ml-1 text-fg-faint">
                          {r.instruments.map((i) => i.split(":")[1]).join(", ")}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className={cn("tabular-nums", r.realized_pnl < 0 ? "text-neg" : "text-pos")}>
                          {inr(r.realized_pnl)}
                        </span>
                        <Badge
                          variant={
                            r.status === "ACTIVE" ? "success" : r.status === "PAUSED" ? "warning" : "default"
                          }
                          className="text-[9px]"
                        >
                          {r.status}
                        </Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                Deployments ({running.length} running)
              </p>
              {running.length === 0 ? (
                <p className="text-xs text-fg-faint">Nothing running.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {running.map((d) => (
                    <li key={d.id}>
                      <Link
                        to={`/deployments/${d.id}`}
                        className="flex items-center justify-between rounded border border-line px-2 py-1 text-xs hover:bg-elevated/60"
                      >
                        <span className="truncate">{d.name}</span>
                        <ModeBadge mode={d.mode} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title={
            <span className="flex items-baseline gap-2">
              Backtests
              <span className="text-[11px] font-normal text-fg-faint">
                {totalBacktests} on record
                {catalog ? ` · ${catalog.meta.catalog_ran}/${catalog.meta.catalog_size} strategy catalog` : ""}
              </span>
            </span>
          }
          className="lg:col-span-2"
          actions={
            <Link to="/backtests" className="text-xs text-accent hover:underline">
              View all
            </Link>
          }
          bodyClassName="p-0"
        >
          <DataTable
            columns={backtestCols}
            rows={recent}
            rowKey={(b) => b.id}
            onRowClick={(b) => navigate(`/backtests/${b.id}`)}
            empty="No backtests yet."
            searchable
            searchPlaceholder="Filter backtests…"
          />
        </SectionCard>

        <SectionCard
          title={`Paper positions (${positions.length + holdings.length})`}
          actions={
            <Link to="/paper" className="text-xs text-accent hover:underline">
              Open
            </Link>
          }
        >
          {positions.length + holdings.length === 0 ? (
            <p className="py-6 text-center text-sm text-fg-faint">
              No open positions. Add an idea above or buy from Paper Trading.
            </p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs">
              {[
                ...holdings.map((h) => ({
                  key: `h-${h.id}`,
                  sym: h.tradingsymbol,
                  tag: "CNC",
                  qty: h.qty,
                  pnl: h.pnl,
                  pct: h.pnl_pct,
                })),
                ...positions.map((p) => ({
                  key: `p-${p.id}`,
                  sym: p.tradingsymbol,
                  tag: p.product,
                  qty: p.net_qty,
                  pnl: p.pnl,
                  pct: p.pnl_pct,
                })),
              ]
                .slice(0, 8)
                .map((r) => (
                  <li
                    key={r.key}
                    className="flex items-center justify-between rounded border border-line px-2 py-1"
                  >
                    <span className="min-w-0">
                      <span className="font-medium text-fg">{r.sym}</span>
                      <span className="ml-1 text-fg-faint">
                        {r.tag} · {r.qty}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "shrink-0 tabular-nums font-medium",
                        (r.pnl ?? 0) < 0 ? "text-neg" : "text-pos",
                      )}
                    >
                      {inr(r.pnl)} {r.pct != null && `(${pctSigned(r.pct)})`}
                    </span>
                  </li>
                ))}
            </ul>
          )}
        </SectionCard>
      </div>

      <p className="text-[11px] text-fg-faint">
        {strategies.data?.length ?? 0} strategies · {totalBacktests} backtests ·{" "}
        {live.length} live. Paper figures are a demo account marked to live prices; not investment
        advice.
      </p>
    </div>
  );
}
