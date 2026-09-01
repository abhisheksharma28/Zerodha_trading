import { useParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBacktest, useBacktestReport, useRunBacktest } from "@/hooks/useBacktests";
import type { BacktestReport } from "@/types/api";

const CHART_GRID = "#262626";
const AXIS = "#737373";
const TIP_STYLE = { background: "#171717", border: "1px solid #404040", fontSize: 12 };

export default function BacktestDetailPage() {
  const { backtestId } = useParams<{ backtestId: string }>();
  const { data: backtest, isLoading } = useBacktest(backtestId);
  const run = useRunBacktest(backtestId ?? "");
  const { data: report } = useBacktestReport(backtestId, backtest?.status === "completed");

  if (isLoading) return <p className="text-sm text-neutral-500">Loading…</p>;
  if (!backtest) return <p className="text-sm text-neutral-500">Backtest not found.</p>;

  const runnable = backtest.status === "pending" || backtest.status === "failed";
  const equity = (backtest.equity_curve ?? []).map(([ts, value], i) => ({ i, ts, equity: value }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {backtest.instrument_universe.join(", ")} backtest
          </h1>
          <p className="text-sm text-neutral-400">
            {new Date(backtest.start_date).toLocaleDateString()} –{" "}
            {new Date(backtest.end_date).toLocaleDateString()} · {backtest.timeframe} · ₹
            {backtest.initial_capital.toLocaleString()}
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
            <p className="font-semibold text-neutral-200">Data quality</p>
            {report.data_quality.errors.map((e) => (
              <p key={e} className="text-red-400">
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

      {report?.metrics && <MetricsGrid m={report.metrics} />}
      {report && <CostBreakdown report={report} />}

      <ChartCard title="Equity curve">
        {equity.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No equity curve yet — this backtest hasn't been executed. Use “Run backtest” above.
          </p>
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer>
              <LineChart data={equity}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
                <YAxis stroke={AXIS} fontSize={12} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={TIP_STYLE}
                  labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""}
                />
                <Line type="monotone" dataKey="equity" stroke="#10b981" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartCard>

      {report && <ReportCharts report={report} />}
      {report && report.trades.length > 0 && <TradesTable report={report} />}
    </div>
  );
}

function ErrorCard({ children }: { children: React.ReactNode }) {
  return (
    <Card className="border-red-500/40 bg-red-500/5">
      <CardContent className="py-3 text-sm text-red-400">{children}</CardContent>
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

function MetricsGrid({ m }: { m: Record<string, number | null> }) {
  const items: [string, string, boolean?][] = [
    ["Net P&L", `₹${fmt(m.net_pnl, 0)}`, (m.net_pnl ?? 0) < 0],
    ["Gross P&L", `₹${fmt(m.gross_pnl, 0)}`],
    ["Total costs", `₹${fmt(m.total_costs, 0)}`, true],
    ["Return", `${fmt(m.return_pct)}%`, (m.return_pct ?? 0) < 0],
    ["CAGR", `${fmt(m.cagr_pct)}%`],
    ["Max drawdown", `${fmt(m.max_drawdown_pct)}%`, true],
    ["Sharpe", fmt(m.sharpe_ratio)],
    ["Sortino", fmt(m.sortino_ratio)],
    ["Calmar", fmt(m.calmar_ratio)],
    ["Profit factor", fmt(m.profit_factor)],
    ["Win rate", `${fmt(m.win_rate_pct)}%`],
    ["Total trades", fmt(m.total_trades, 0)],
    ["Avg trade", `₹${fmt(m.avg_trade, 0)}`],
    ["Avg winner", `₹${fmt(m.avg_winner, 0)}`],
    ["Avg loser", `₹${fmt(m.avg_loser, 0)}`, true],
    ["Largest winner", `₹${fmt(m.largest_winner, 0)}`],
    ["Largest loser", `₹${fmt(m.largest_loser, 0)}`, true],
    ["Max consec. losses", fmt(m.max_consecutive_losses, 0), true],
    ["Turnover", `${fmt(m.turnover_ratio)}x`],
    ["Capital utilization", `${fmt(m.capital_utilization_pct)}%`],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
      {items.map(([label, value, neg]) => (
        <Card key={label}>
          <CardContent className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
            <p className={`mt-1 text-lg font-semibold ${neg ? "text-red-400" : "text-neutral-100"}`}>
              {value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
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
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-neutral-300">
          {rows.map((k) => (
            <span key={k}>
              <span className="text-neutral-500">{k}</span> ₹{fmt(b[k], 1)}
            </span>
          ))}
          <span className="font-semibold">
            <span className="text-neutral-500">total</span> ₹{fmt(b.total, 1)}
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
      <ChartCard title="Drawdown">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <AreaChart data={dd}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
              <YAxis stroke={AXIS} fontSize={12} />
              <Tooltip contentStyle={TIP_STYLE} labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""} />
              <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="#ef444433" strokeWidth={1.5} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard title="Monthly returns (%)">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <BarChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="k" stroke={AXIS} fontSize={10} />
              <YAxis stroke={AXIS} fontSize={12} />
              <Tooltip contentStyle={TIP_STYLE} />
              <Bar dataKey="v">
                {monthly.map((d, i) => (
                  <Cell key={i} fill={d.v >= 0 ? "#10b981" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      {bars.length > 0 && (
        <ChartCard title="Trade return distribution (%)">
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <BarChart data={bars}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis dataKey="x" stroke={AXIS} fontSize={10} />
                <YAxis stroke={AXIS} fontSize={12} allowDecimals={false} />
                <Tooltip contentStyle={TIP_STYLE} />
                <Bar dataKey="c">
                  {bars.map((d, i) => (
                    <Cell key={i} fill={d.mid >= 0 ? "#10b981" : "#ef4444"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      )}

      <ChartCard title="Exposure (% of capital)">
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <AreaChart data={report.charts.exposure_curve.map(([ts, v], i) => ({ i, ts, e: v }))}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
              <XAxis dataKey="i" stroke={AXIS} fontSize={12} />
              <YAxis stroke={AXIS} fontSize={12} />
              <Tooltip contentStyle={TIP_STYLE} labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""} />
              <Area type="monotone" dataKey="e" stroke="#0ea5e9" fill="#0ea5e933" strokeWidth={1.5} />
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
            <thead className="sticky top-0 bg-neutral-900 text-neutral-500">
              <tr>
                <th className="py-1 pr-3">Instrument</th>
                <th className="py-1 pr-3">Dir</th>
                <th className="py-1 pr-3">Qty</th>
                <th className="py-1 pr-3">Entry</th>
                <th className="py-1 pr-3">Exit</th>
                <th className="py-1 pr-3">Bars</th>
                <th className="py-1 pr-3">Net P&L</th>
                <th className="py-1">Return</th>
              </tr>
            </thead>
            <tbody className="text-neutral-300">
              {report.trades.map((t, i) => (
                <tr key={i} className="border-t border-neutral-800">
                  <td className="py-1.5 pr-3">{t.instrument}</td>
                  <td className="py-1.5 pr-3">{t.direction}</td>
                  <td className="py-1.5 pr-3">{t.quantity}</td>
                  <td className="py-1.5 pr-3">{fmt(t.entry_price)}</td>
                  <td className="py-1.5 pr-3">
                    {fmt(t.exit_price)}
                    {t.is_open && <span className="text-neutral-500"> (open)</span>}
                  </td>
                  <td className="py-1.5 pr-3">{t.bars_held}</td>
                  <td className={`py-1.5 pr-3 ${t.net_pnl < 0 ? "text-red-400" : "text-emerald-400"}`}>
                    ₹{fmt(t.net_pnl, 0)}
                  </td>
                  <td className={t.return_pct < 0 ? "text-red-400" : "text-emerald-400"}>
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
