import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import type { SeriesMarker, Time } from "lightweight-charts";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PriceChart } from "@/components/PriceChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBacktest, useBacktestReport, useRunBacktest } from "@/hooks/useBacktests";
import { useCandles } from "@/hooks/useCandles";
import { inr } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import type { BacktestDiagnostics, BacktestReport } from "@/types/api";

// CSS vars so charts re-colour with the light/dark theme (see src/index.css).
const CHART_GRID = "var(--color-line-strong)";
const AXIS = "var(--color-fg-faint)";
const TIP_STYLE = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-line-strong)",
  color: "var(--color-fg)",
  fontSize: 12,
};
const LABEL_FILL = "var(--color-fg-muted)";

const compactNum = (v: number) =>
  Math.abs(v) >= 1e7
    ? `${(v / 1e7).toFixed(2)}Cr`
    : Math.abs(v) >= 1e5
      ? `${(v / 1e5).toFixed(2)}L`
      : Math.abs(v) >= 1e3
        ? `${(v / 1e3).toFixed(1)}k`
        : `${v.toFixed(0)}`;
const rupeeTick = (v: number) => `₹${compactNum(v)}`;
const pctTick = (v: number) => `${v.toFixed(v >= 10 || v <= -10 ? 0 : 1)}%`;
const toNum = (v: unknown) => (typeof v === "number" ? v : Number(v));
const pctLabel = (v: unknown) => {
  const n = toNum(v);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "";
};
// recharts Tooltip formatter — coerce the loose ValueType to a number.
const tipFmt =
  (fn: (n: number) => string, name: string) =>
  (v: unknown): [string, string] => [fn(toNum(v)), name];

// Value label for dense line/area series: only first, last and evenly spaced
// interior points get a label, so a long curve stays readable.
const sparseLabel =
  (total: number, format: (v: number) => string) =>
  (props: {
    index?: number;
    value?: unknown;
    x?: number | string;
    y?: number | string;
  }) => {
    const { index, value, x, y } = props;
    const nx = toNum(x);
    const ny = toNum(y);
    const nv = toNum(value);
    if (index == null || !Number.isFinite(nv) || !Number.isFinite(nx) || !Number.isFinite(ny))
      return null;
    const step = Math.max(1, Math.ceil(total / 6));
    if (index !== 0 && index !== total - 1 && index % step !== 0) return null;
    return (
      <text x={nx} y={ny - 6} fontSize={10} fill={LABEL_FILL} textAnchor="middle">
        {format(nv)}
      </text>
    );
  };

export default function BacktestDetailPage() {
  const { backtestId } = useParams<{ backtestId: string }>();
  const { data: backtest, isLoading } = useBacktest(backtestId);
  const run = useRunBacktest(backtestId ?? "");
  const { data: report } = useBacktestReport(backtestId, backtest?.status === "completed");

  if (isLoading) return <p className="text-sm text-fg-faint">Loading…</p>;
  if (!backtest) return <p className="text-sm text-fg-faint">Backtest not found.</p>;

  const runnable = backtest.status === "pending" || backtest.status === "failed";
  const equity = (backtest.equity_curve ?? []).map(([ts, value], i) => ({ i, ts, equity: value }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {backtest.instrument_universe.join(", ")} backtest
          </h1>
          <p className="text-sm text-fg-muted">
            {new Date(backtest.start_date).toLocaleDateString()} –{" "}
            {new Date(backtest.end_date).toLocaleDateString()} · {backtest.timeframe} ·{" "}
            {inr(backtest.initial_capital)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {runnable && (
            <Button onClick={() => run.mutate({})} disabled={run.isPending}>
              {run.isPending
                ? "Running…"
                : backtest.status === "failed"
                  ? "Re-run backtest"
                  : "Run backtest"}
            </Button>
          )}
          <Badge variant={backtest.status === "completed" ? "success" : "default"}>
            {backtest.status}
          </Badge>
        </div>
      </div>

      {run.isError && <ErrorCard>{(run.error as Error).message}</ErrorCard>}
      {backtest.error_message && <ErrorCard>{backtest.error_message}</ErrorCard>}

      {report?.data_quality && (report.data_quality.warnings.length > 0 || !report.data_quality.ok) && (
        <Card
          className={
            report.data_quality.ok
              ? "border-amber-500/40 bg-amber-500/5"
              : "border-red-500/40 bg-red-500/5"
          }
        >
          <CardContent className="py-3 text-xs">
            <p className="font-semibold text-fg">Data quality</p>
            {report.data_quality.errors.map((e) => (
              <p key={e} className="text-neg">
                • {e}
              </p>
            ))}
            {report.data_quality.warnings.map((w) => (
              <p key={w} className="text-amber-400/90">
                • {w}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {report && report.no_trades_analysis?.length > 0 && (
        <NoTradesPanel report={report} />
      )}
      {report && <DiagnosticsCard report={report} />}

      {report?.metrics && <MetricsGrid m={report.metrics} />}
      {report && <CostBreakdown report={report} />}

      <ChartCard title="Equity curve">
        {equity.length === 0 ? (
          <p className="text-sm text-fg-faint">
            No equity curve yet — this backtest hasn't been executed. Use “Run backtest” above.
          </p>
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer>
              <LineChart data={equity} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
                <YAxis
                  stroke={AXIS}
                  fontSize={12}
                  width={70}
                  domain={["auto", "auto"]}
                  tickFormatter={rupeeTick}
                />
                <Tooltip
                  contentStyle={TIP_STYLE}
                  formatter={tipFmt((n) => `₹${fmt(n, 0)}`, "Equity")}
                  labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""}
                />
                <Line type="monotone" dataKey="equity" stroke="var(--color-accent)" dot={false} strokeWidth={2}>
                  <LabelList dataKey="equity" content={sparseLabel(equity.length, rupeeTick)} />
                </Line>
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartCard>

      {report && backtest && report.trades.length > 0 && (
        <PriceTradesChart
          report={report}
          timeframe={backtest.timeframe}
          from={backtest.start_date}
          to={backtest.end_date}
        />
      )}
      {report && <ReportCharts report={report} />}
      {report && report.trades.length > 0 && <TradesTable report={report} />}
    </div>
  );
}

function PriceTradesChart({
  report,
  timeframe,
  from,
  to,
}: {
  report: BacktestReport;
  timeframe: string;
  from: string;
  to: string;
}) {
  const { theme } = useTheme();
  const symbols = useMemo(
    () => [...new Set(report.trades.map((t) => t.instrument))],
    [report.trades],
  );
  const [sym, setSym] = useState(symbols[0]);
  const { data } = useCandles(sym ? `NSE:${sym}` : undefined, timeframe, { from, to });
  const candles = data?.available ? (data.candles ?? []) : [];

  const markers = useMemo<SeriesMarker<Time>[]>(() => {
    // backend candle epochs are shifted +5:30 so the chart reads IST; markers must match
    const IST = 5.5 * 3600;
    const out: SeriesMarker<Time>[] = [];
    for (const t of report.trades) {
      if (t.instrument !== sym) continue;
      const long = t.direction === "long";
      if (t.entry_time) {
        out.push({
          time: (Math.floor(Date.parse(t.entry_time) / 1000) + IST) as Time,
          position: long ? "belowBar" : "aboveBar",
          color: long ? "var(--color-pos)" : "var(--color-neg)",
          shape: long ? "arrowUp" : "arrowDown",
          text: `${long ? "BUY" : "SELL"} ${t.entry_price}`,
        });
      }
      if (t.exit_time && !t.is_open) {
        out.push({
          time: (Math.floor(Date.parse(t.exit_time) / 1000) + IST) as Time,
          position: long ? "aboveBar" : "belowBar",
          color: "var(--color-fg-faint)",
          shape: long ? "arrowDown" : "arrowUp",
          text: `exit ${t.exit_price}`,
        });
      }
    }
    return out.sort((a, b) => (a.time as number) - (b.time as number));
  }, [report.trades, sym]);

  return (
    <ChartCard title="Price & trades">
      {symbols.length > 1 && (
        <div className="mb-2">
          <select
            value={sym}
            onChange={(e) => setSym(e.target.value)}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg"
          >
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      )}
      {data && !data.available ? (
        <p className="py-8 text-center text-xs text-fg-faint">{data.reason}</p>
      ) : candles.length === 0 ? (
        <p className="py-8 text-center text-xs text-fg-faint">Loading price history…</p>
      ) : (
        <PriceChart
          candles={candles}
          markers={markers}
          themeKey={`${theme}-${sym}-${timeframe}`}
          height={420}
        />
      )}
    </ChartCard>
  );
}

function ErrorCard({ children }: { children: React.ReactNode }) {
  return (
    <Card className="border-red-500/40 bg-red-500/5">
      <CardContent className="py-3 text-sm text-neg">{children}</CardContent>
    </Card>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Backtest trade timestamps are IST wall-clock (naive or +05:30). Show the wall
// clock as-is — parsing through Date would re-interpret it in the viewer's zone.
const istDateTime = (raw: string | null | undefined) => {
  if (!raw) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(raw.trim());
  if (!m) return raw;
  const [, y, mo, d, hh, mm] = m;
  const mon = MONTHS[Number(mo) - 1] ?? mo;
  return `${d} ${mon} ${y} · ${hh}:${mm}`;
};

function MetricsGrid({ m }: { m: Record<string, number | null> }) {
  const items: [string, string, boolean?][] = [
    ["Net P&L", inr(m.net_pnl), (m.net_pnl ?? 0) < 0],
    ["Gross P&L", inr(m.gross_pnl)],
    ["Total costs", inr(m.total_costs), true],
    ["Return", `${fmt(m.return_pct)}%`, (m.return_pct ?? 0) < 0],
    ["CAGR", `${fmt(m.cagr_pct)}%`],
    ["Max drawdown", `${fmt(m.max_drawdown_pct)}%`, true],
    ["Sharpe", fmt(m.sharpe_ratio)],
    ["Sortino", fmt(m.sortino_ratio)],
    ["Calmar", fmt(m.calmar_ratio)],
    ["Profit factor", fmt(m.profit_factor)],
    ["Win rate", `${fmt(m.win_rate_pct)}%`],
    ["Total trades", fmt(m.total_trades, 0)],
    ["Avg trade", inr(m.avg_trade)],
    ["Avg winner", inr(m.avg_winner)],
    ["Avg loser", inr(m.avg_loser), true],
    ["Largest winner", inr(m.largest_winner)],
    ["Largest loser", inr(m.largest_loser), true],
    ["Max consec. losses", fmt(m.max_consecutive_losses, 0), true],
    ["Turnover", `${fmt(m.turnover_ratio)}x`],
    ["Capital utilization", `${fmt(m.capital_utilization_pct)}%`],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
      {items.map(([label, value, neg]) => (
        <Card key={label}>
          <CardContent className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-fg-faint">{label}</p>
            <p className={`mt-1 text-lg font-semibold ${neg ? "text-neg" : "text-fg"}`}>
              {value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function NoTradesPanel({ report }: { report: BacktestReport }) {
  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardHeader>
        <CardTitle className="text-amber-300">No trades were generated</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-fg-muted">
        <ul className="list-disc space-y-1 pl-5">
          {report.no_trades_analysis.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function DiagnosticsCard({ report }: { report: BacktestReport }) {
  const d = report.diagnostics as BacktestDiagnostics;
  if (!d || !("total_bars" in d)) return null;
  const chip = (label: string, value: React.ReactNode) => (
    <span className="rounded bg-elevated px-2 py-0.5 text-xs text-fg-muted">
      <span className="text-fg-faint">{label}</span> {value}
    </span>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Run diagnostics</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5">
          {chip("bars", fmt(d.total_bars, 0))}
          {chip("instruments", d.instruments.length)}
          {chip("orders", fmt(d.orders_submitted, 0))}
          {chip("fills", fmt(d.fills, 0))}
          {d.rejected_orders > 0 && chip("rejected", fmt(d.rejected_orders, 0))}
          {d.first_bar_ts && chip("span", `${d.first_bar_ts.slice(0, 10)} → ${d.last_bar_ts?.slice(0, 10)}`)}
        </div>
        {Object.keys(d.signals).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-xs text-fg-faint">signals:</span>
            {Object.entries(d.signals).map(([k, v]) => chip(k, v))}
          </div>
        )}
        {Object.keys(d.rejection_reasons).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-xs text-fg-faint">rejections:</span>
            {Object.entries(d.rejection_reasons).map(([k, v]) => chip(k, v))}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs text-fg-faint">bars / instrument:</span>
          {Object.entries(d.bars_by_instrument).map(([k, v]) => chip(k, fmt(v, 0)))}
        </div>
      </CardContent>
    </Card>
  );
}

function CostBreakdown({ report }: { report: BacktestReport }) {
  const b = report.cost_breakdown;
  const rows = ["brokerage", "stt", "exchange_txn", "gst", "sebi", "stamp_duty", "slippage"].filter(
    (k) => b[k] != null,
  );
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost breakdown (Indian charges — approximate)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-muted">
          {rows.map((k) => (
            <span key={k}>
              <span className="text-fg-faint">{k}</span> {inr(b[k], 1)}
            </span>
          ))}
          <span className="font-semibold">
            <span className="text-fg-faint">total</span> {inr(b.total, 1)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function ReportCharts({ report }: { report: BacktestReport }) {
  const dd = report.charts.drawdown_curve.map(([ts, v], i) => ({ i, ts, dd: v }));
  const monthly = Object.entries(report.charts.monthly_returns).map(([k, v]) => ({ k, v }));
  const hist = report.charts.trade_return_distribution;
  const bars = (hist.counts ?? []).map((c, i) => ({
    x: hist.bin_edges ? `${hist.bin_edges[i]?.toFixed(1)}` : String(i),
    c,
    mid: hist.bin_edges ? (hist.bin_edges[i] + hist.bin_edges[i + 1]) / 2 : 0,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <ChartCard title="Drawdown (%)">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <AreaChart data={dd} margin={{ top: 12, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
              <YAxis stroke={AXIS} fontSize={12} width={52} tickFormatter={pctTick} />
              <Tooltip
                contentStyle={TIP_STYLE}
                formatter={tipFmt((n) => `${fmt(n, 2)}%`, "Drawdown")}
                labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""}
              />
              <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="#ef444433" strokeWidth={1.5}>
                <LabelList dataKey="dd" content={sparseLabel(dd.length, (v) => `${v.toFixed(1)}%`)} />
              </Area>
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard title="Monthly returns (%)">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <BarChart data={monthly} margin={{ top: 16, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="k" stroke={AXIS} fontSize={10} />
              <YAxis stroke={AXIS} fontSize={12} width={52} tickFormatter={pctTick} />
              <Tooltip contentStyle={TIP_STYLE} formatter={tipFmt((n) => `${fmt(n, 2)}%`, "Return")} />
              <Bar dataKey="v">
                {monthly.map((d, i) => (
                  <Cell key={i} fill={d.v >= 0 ? "var(--color-pos)" : "var(--color-neg)"} />
                ))}
                <LabelList
                  dataKey="v"
                  position="top"
                  fontSize={10}
                  fill={LABEL_FILL}
                  formatter={pctLabel}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      {bars.length > 0 && (
        <ChartCard title="Trade return distribution (count)">
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <BarChart data={bars} margin={{ top: 16, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="x" stroke={AXIS} fontSize={10} />
                <YAxis stroke={AXIS} fontSize={12} allowDecimals={false} />
                <Tooltip contentStyle={TIP_STYLE} formatter={tipFmt((n) => String(n), "Trades")} />
                <Bar dataKey="c">
                  {bars.map((d, i) => (
                    <Cell key={i} fill={d.mid >= 0 ? "var(--color-pos)" : "var(--color-neg)"} />
                  ))}
                  <LabelList dataKey="c" position="top" fontSize={10} fill={LABEL_FILL} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      )}

      <ChartCard title="Exposure (% of capital)">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <AreaChart
              data={report.charts.exposure_curve.map(([ts, v], i) => ({ i, ts, e: v }))}
              margin={{ top: 12, right: 16, bottom: 0, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
              <YAxis stroke={AXIS} fontSize={12} width={52} tickFormatter={pctTick} />
              <Tooltip
                contentStyle={TIP_STYLE}
                formatter={tipFmt((n) => `${fmt(n, 1)}%`, "Exposure")}
                labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""}
              />
              <Area type="monotone" dataKey="e" stroke="#0ea5e9" fill="#0ea5e933" strokeWidth={1.5}>
                <LabelList
                  dataKey="e"
                  content={sparseLabel(
                    report.charts.exposure_curve.length,
                    (v) => `${v.toFixed(0)}%`,
                  )}
                />
              </Area>
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>
    </div>
  );
}

function TradesTable({ report }: { report: BacktestReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Trades ({report.trades.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-fg-faint">
              <tr>
                <th className="py-1 pr-3">Instrument</th>
                <th className="py-1 pr-3">Dir</th>
                <th className="py-1 pr-3">Qty</th>
                <th className="py-1 pr-3">Entry time</th>
                <th className="py-1 pr-3">Entry</th>
                <th className="py-1 pr-3">Exit time</th>
                <th className="py-1 pr-3">Exit</th>
                <th className="py-1 pr-3">Bars</th>
                <th className="py-1 pr-3">Net P&L</th>
                <th className="py-1">Return</th>
              </tr>
            </thead>
            <tbody className="text-fg-muted">
              {report.trades.map((t, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1.5 pr-3">{t.instrument}</td>
                  <td className="py-1.5 pr-3">{t.direction}</td>
                  <td className="py-1.5 pr-3">{t.quantity}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums">{istDateTime(t.entry_time)}</td>
                  <td className="py-1.5 pr-3">{fmt(t.entry_price)}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums">
                    {t.is_open ? <span className="text-fg-faint">open</span> : istDateTime(t.exit_time)}
                  </td>
                  <td className="py-1.5 pr-3">{fmt(t.exit_price)}</td>
                  <td className="py-1.5 pr-3">{t.bars_held}</td>
                  <td className={`py-1.5 pr-3 ${t.net_pnl < 0 ? "text-neg" : "text-pos"}`}>
                    {inr(t.net_pnl)}
                  </td>
                  <td className={t.return_pct < 0 ? "text-neg" : "text-pos"}>
                    {fmt(t.return_pct)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
