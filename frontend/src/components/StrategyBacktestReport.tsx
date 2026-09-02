import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { BacktestReport } from "@/api/strategyLibrary";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useBacktestReport,
  useDownloadBacktestReportPdf,
  useNifty200Universe,
} from "@/hooks/useStrategyLibrary";
import { inr, inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { StrategyTemplateDetail } from "@/types/api";

const FALLBACK_SYMBOLS = [
  "NSE:RELIANCE",
  "NSE:INFY",
  "NSE:HDFCBANK",
  "NSE:ICICIBANK",
  "NSE:TCS",
];

function Metric({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-md border border-line bg-elevated px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div
        className={cn(
          "font-mono text-sm tabular-nums",
          tone === "pos" && "text-pos",
          tone === "neg" && "text-neg",
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function StrategyBacktestReport({ template: t }: { template: StrategyTemplateDetail }) {
  const presetNames = Object.keys(t.presets);
  const tfAllowed = t.supported_timeframes ?? undefined;

  const universe = useNifty200Universe();
  const [symbols, setSymbols] = useState<string[]>([]);
  const effectiveSymbols = symbols.length
    ? symbols
    : (universe.data ?? FALLBACK_SYMBOLS).slice(0, 5);

  const [preset, setPreset] = useState(
    presetNames.includes("balanced") ? "balanced" : presetNames[0],
  );
  const [timeframe, setTimeframe] = useState(
    tfAllowed?.includes("1d") ? "1d" : (tfAllowed?.[0] ?? "1d"),
  );
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [capital, setCapital] = useState(1_000_000);

  const run = useBacktestReport(t.slug);
  const pdf = useDownloadBacktestReportPdf(t.slug);

  const payload = () => ({
    symbols: effectiveSymbols,
    timeframe,
    preset,
    capital,
    start: start || undefined,
    end: end || undefined,
  });

  const report = run.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest report</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-xs text-fg-faint">
          Run this template over any NIFTY 200 names, review the results, and download a PDF.
          Same engine, cost model and metrics as a saved backtest. Research only — not advice.
        </p>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="flex flex-col gap-1.5 lg:col-span-2">
            <Label>Symbols (search NIFTY 200 — defaults to 5 large caps)</Label>
            <InstrumentSearch value={symbols} onChange={setSymbols} multiple />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rep-preset">Preset</Label>
            <select
              id="rep-preset"
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {presetNames.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Timeframe</Label>
            <TimeframeSelect value={timeframe} onChange={setTimeframe} allowed={tfAllowed} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rep-start">Start (optional)</Label>
            <Input id="rep-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rep-end">End (optional)</Label>
            <Input id="rep-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rep-cap">Starting capital (₹)</Label>
            <Input
              id="rep-cap"
              type="number"
              value={capital}
              min={1000}
              step={100000}
              onChange={(e) => setCapital(Number(e.target.value) || 0)}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={run.isPending} onClick={() => run.mutate(payload())}>
            {run.isPending ? "Running…" : "Run backtest"}
          </Button>
          <Button
            variant="outline"
            disabled={pdf.isPending}
            onClick={() => pdf.mutate(payload())}
          >
            {pdf.isPending ? "Building PDF…" : "Download PDF"}
          </Button>
          {run.isError && (
            <span className="text-xs text-neg">{(run.error as Error).message}</span>
          )}
          {pdf.isError && (
            <span className="text-xs text-neg">{(pdf.error as Error).message}</span>
          )}
        </div>

        {report && <ReportView report={report} />}
      </CardContent>
    </Card>
  );
}

function ReportView({ report }: { report: BacktestReport }) {
  const m = report.metrics;
  const equity = useMemo(
    () =>
      report.equity_curve.map(([ts, v]) => ({
        t: ts.slice(0, 10),
        v: Math.round(v),
      })),
    [report.equity_curve],
  );
  const pf = m.profit_factor;

  return (
    <div className="flex flex-col gap-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm">
          <span className="font-semibold">{report.strategy_name}</span>{" "}
          <span className="text-fg-faint">
            · {report.preset} · {report.timeframe} · {report.start} → {report.end} ·{" "}
            {report.used_symbols.join(", ")}
          </span>
        </div>
        <span className="text-[10px] text-fg-faint">generated {report.generated_at}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Metric
          label="Total return"
          value={`${num(m.return_pct)}%`}
          tone={(m.return_pct ?? 0) >= 0 ? "pos" : "neg"}
        />
        <Metric label="CAGR" value={`${num(m.cagr_pct)}%`} />
        <Metric label="Sharpe" value={num(m.sharpe_ratio)} />
        <Metric label="Sortino" value={num(m.sortino_ratio)} />
        <Metric label="Max DD" value={`${num(m.max_drawdown_pct)}%`} tone="neg" />
        <Metric
          label="Net P&L"
          value={inrCompact(m.net_pnl)}
          tone={(m.net_pnl ?? 0) >= 0 ? "pos" : "neg"}
        />
        <Metric label="Costs" value={inrCompact(m.total_costs)} />
        <Metric label="Trades" value={String(m.total_trades ?? 0)} />
        <Metric label="Win rate" value={`${num(m.win_rate_pct)}%`} />
        <Metric label="Profit factor" value={pf == null ? "∞" : num(pf)} />
      </div>

      {equity.length > 1 && (
        <div className="h-56 w-full">
          <ResponsiveContainer>
            <AreaChart data={equity} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
              <defs>
                <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeOpacity={0.15} vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={48} />
              <YAxis
                tick={{ fontSize: 10 }}
                width={64}
                tickFormatter={(v) => inrCompact(v as number)}
                domain={["auto", "auto"]}
              />
              <Tooltip
                formatter={(v) => inr(v as number)}
                labelStyle={{ color: "var(--color-fg)" }}
                contentStyle={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-line-strong)",
                  fontSize: 12,
                }}
              />
              <Area
                type="monotone"
                dataKey="v"
                stroke="var(--color-accent)"
                strokeWidth={1.5}
                fill="url(#eqfill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {report.per_symbol.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-fg-faint">
              <tr>
                <th className="py-1 pr-4">Symbol</th>
                <th className="py-1 pr-4">Trades</th>
                <th className="py-1 pr-4">Win %</th>
                <th className="py-1 pr-4">Net P&L</th>
                <th className="py-1 pr-4">Avg</th>
                <th className="py-1 pr-4">Best</th>
                <th className="py-1">Worst</th>
              </tr>
            </thead>
            <tbody className="text-fg-muted">
              {report.per_symbol.map((s) => (
                <tr key={s.symbol} className="border-t border-line">
                  <td className="py-1.5 pr-4 font-mono text-[11px]">{s.symbol}</td>
                  <td className="py-1.5 pr-4">{s.trades}</td>
                  <td className="py-1.5 pr-4">{num(s.win_rate_pct)}%</td>
                  <td
                    className={cn(
                      "py-1.5 pr-4 tabular-nums",
                      s.net_pnl >= 0 ? "text-pos" : "text-neg",
                    )}
                  >
                    {inr(s.net_pnl)}
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums">{inr(s.avg_trade)}</td>
                  <td className="py-1.5 pr-4 tabular-nums">{inr(s.largest_winner)}</td>
                  <td className="py-1.5 tabular-nums">{inr(s.largest_loser)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report.skipped.length > 0 && (
        <p className="text-xs text-amber-500">
          Skipped: {report.skipped.map((s) => `${s.symbol} (${s.reason})`).join("; ")}
        </p>
      )}

      {(report.data_quality?.warnings?.length ?? 0) > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-500">
          {report.data_quality.warnings!.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <details className="text-xs text-fg-faint">
        <summary className="cursor-pointer">Caveats</summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          {report.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
