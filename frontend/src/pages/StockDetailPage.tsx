import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { Time } from "lightweight-charts";
import { Bell, FlaskConical, LineChart as LineChartIcon } from "lucide-react";

import { stocksApi } from "@/api/stocks";
import { PageHeader } from "@/components/PageHeader";
import { PriceChart } from "@/components/PriceChart";
import { SectionCard } from "@/components/SectionCard";
import { Card, CardContent } from "@/components/ui/card";
import { useCandles } from "@/hooks/useCandles";
import { useLiveTick } from "@/hooks/useLiveTick";
import { useMarketOverview } from "@/hooks/useMarket";
import { useNow } from "@/hooks/useNow";
import { ema, rsi, sma, vwap, macd, bollinger, type Candle } from "@/lib/indicators";
import { inrCompact } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const num = (v: unknown, d = 2) =>
  typeof v === "number" && isFinite(v)
    ? v.toLocaleString("en-IN", { maximumFractionDigits: d })
    : "N/A";
const last = <T,>(a: { value: T }[]): T | undefined => (a.length ? a[a.length - 1].value : undefined);

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "1d", "1w"] as const;
const PERIODS: { label: string; days: number; tf: string }[] = [
  { label: "Day", days: 1, tf: "5m" },
  { label: "Week", days: 7, tf: "15m" },
  { label: "Month", days: 31, tf: "1h" },
  { label: "3M", days: 92, tf: "1d" },
  { label: "6M", days: 183, tf: "1d" },
  { label: "1Y", days: 365, tf: "1d" },
  { label: "5Y", days: 1825, tf: "1w" },
  { label: "Max", days: 4000, tf: "1w" },
];

// --- recommendation scoring -----------------------------------------

interface Gauge {
  label: string;
  buy: number;
  neutral: number;
  sell: number;
  verdict: string;
  tone: "pos" | "neg" | "muted";
}

function verdictOf(net: number, total: number): { verdict: string; tone: Gauge["tone"] } {
  const r = total ? net / total : 0;
  if (r >= 0.5) return { verdict: "Strong Buy", tone: "pos" };
  if (r >= 0.2) return { verdict: "Buy", tone: "pos" };
  if (r <= -0.5) return { verdict: "Strong Sell", tone: "neg" };
  if (r <= -0.2) return { verdict: "Sell", tone: "neg" };
  return { verdict: "Neutral", tone: "muted" };
}

function toGauge(label: string, signals: number[]): Gauge {
  const buy = signals.filter((s) => s > 0).length;
  const sell = signals.filter((s) => s < 0).length;
  const neutral = signals.length - buy - sell;
  const { verdict, tone } = verdictOf(buy - sell, signals.length);
  return { label, buy, neutral, sell, verdict, tone };
}

function recommendations(candles: Candle[]): Gauge[] | null {
  if (candles.length < 60) return null;
  const price = candles[candles.length - 1].close;
  const s20 = last(sma(candles, 20));
  const e20 = last(ema(candles, 20));
  const e50 = last(ema(candles, 50));
  const e200 = last(ema(candles, 200));
  const rv = last(rsi(candles, 14));
  const vw = last(vwap(candles));
  const m = macd(candles);
  const hist = m.hist.length ? m.hist[m.hist.length - 1].value : undefined;
  const bb = bollinger(candles, 20);
  const bbUpper = bb.upper.length ? bb.upper[bb.upper.length - 1].value : undefined;
  const bbLower = bb.lower.length ? bb.lower[bb.lower.length - 1].value : undefined;
  const roc =
    candles.length > 11 ? price / candles[candles.length - 11].close - 1 : undefined;

  const cmp = (a?: number, b?: number) => (a == null || b == null ? 0 : a > b ? 1 : a < b ? -1 : 0);
  const ma = [cmp(price, s20), cmp(price, e20), cmp(price, e50), cmp(price, e200)];
  const ti = [
    rv == null ? 0 : rv > 70 ? -1 : rv < 30 ? 1 : rv > 55 ? 1 : rv < 45 ? -1 : 0,
    hist == null ? 0 : hist > 0 ? 1 : -1,
    cmp(price, vw),
    roc == null ? 0 : roc > 0.01 ? 1 : roc < -0.01 ? -1 : 0,
    bbUpper != null && price > bbUpper ? -1 : bbLower != null && price < bbLower ? 1 : 0,
  ];

  return [
    toGauge("Technical indicators", ti),
    toGauge("General assessment", [...ma, ...ti]),
    toGauge("Moving average", ma),
  ];
}

// --- donut ----------------------------------------------------------

function Donut({ g }: { g: Gauge }) {
  const total = Math.max(1, g.buy + g.neutral + g.sell);
  const r = 34;
  const c = 2 * Math.PI * r;
  const color = g.tone === "pos" ? "var(--color-pos)" : g.tone === "neg" ? "var(--color-neg)" : "var(--color-accent)";
  const filled = ((g.buy + g.sell) / total) * c;
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative h-24 w-24">
        <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
          <circle cx="40" cy="40" r={r} fill="none" stroke="var(--color-line-strong)" strokeWidth="7" />
          <circle
            cx="40"
            cy="40"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={`${filled} ${c - filled}`}
          />
        </svg>
        <span
          className={cn(
            "absolute inset-0 flex items-center justify-center text-sm font-semibold",
            g.tone === "pos" ? "text-pos" : g.tone === "neg" ? "text-neg" : "text-fg",
          )}
        >
          {g.verdict.replace("Strong ", "")}
        </span>
      </div>
      <p className="text-[11px] text-fg-faint">{g.label}</p>
      <p className="text-[10px] text-fg-faint">
        Buy {g.buy} · Nl {g.neutral} · Sell {g.sell}
      </p>
    </div>
  );
}

function RangeBar({ low, high, value }: { low: number; high: number; value: number }) {
  const pct = high > low ? ((value - low) / (high - low)) * 100 : 50;
  return (
    <div className="relative mt-1.5 h-1.5 w-full rounded-full bg-elevated">
      <div className="absolute h-full rounded-full bg-accent/50" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      <div
        className="absolute -top-1 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-surface bg-accent"
        style={{ left: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

// --- page ---------------------------------------------------------

export default function StockDetailPage() {
  const { exchange = "NSE", symbol = "" } = useParams();
  const ref = `${exchange}:${symbol}`;
  const { theme } = useTheme();
  const now = useNow(1000);

  const { data } = useQuery({
    queryKey: ["stock", exchange, symbol],
    queryFn: () => stocksApi.quickLook(exchange, symbol),
    refetchInterval: 6_000,
    staleTime: 0,
  });
  const { tick, status: streamStatus } = useLiveTick(ref);

  const rest = data?.quote?.available ? data.quote : null;
  const q = useMemo(() => {
    if (!rest) return null;
    if (!tick || tick.ltp == null) return rest;
    const ltp = tick.ltp;
    const pc = rest.prev_close;
    return {
      ...rest,
      ltp,
      change: pc != null ? ltp - pc : rest.change,
      change_pct: pc ? ((ltp - pc) / pc) * 100 : rest.change_pct,
      high: tick.ohlc ? Math.max(rest.high ?? ltp, tick.ohlc.high) : rest.high,
      low: tick.ohlc ? Math.min(rest.low ?? ltp, tick.ohlc.low) : rest.low,
      volume: tick.volume ?? rest.volume,
    };
  }, [rest, tick]);
  const chgPos = (q?.change_pct ?? 0) >= 0;

  // chart
  const [periodIdx, setPeriodIdx] = useState(5); // 1Y
  const [timeframe, setTimeframe] = useState(PERIODS[5].tf);
  const period = PERIODS[periodIdx];
  const { data: candleResp, isFetching: candlesFetching } = useCandles(ref, timeframe, {
    days: period.days,
    refetchMs: timeframe === "1d" || timeframe === "1w" ? 60_000 : 10_000,
  });
  const candles = useMemo<Candle[]>(
    () => (candleResp?.available ? (candleResp.candles ?? []) : []),
    [candleResp],
  );

  const [chartApi, setChartApi] = useState<{ series: { update: (b: unknown) => void } } | null>(null);
  const liveLastRef = useRef<Candle | null>(null);
  useEffect(() => {
    liveLastRef.current = null;
  }, [candles]);
  useEffect(() => {
    if (!tick || tick.ltp == null || !chartApi || candles.length === 0) return;
    const base = liveLastRef.current ?? candles[candles.length - 1];
    const merged: Candle = {
      ...base,
      high: Math.max(base.high, tick.ltp),
      low: Math.min(base.low, tick.ltp),
      close: tick.ltp,
    };
    liveLastRef.current = merged;
    chartApi.series.update({
      time: merged.time as Time,
      open: merged.open,
      high: merged.high,
      low: merged.low,
      close: merged.close,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, chartApi]);

  // recommendations (from daily candles)
  const { data: dailyResp } = useCandles(ref, "1d", 260);
  const dailyCandles = useMemo<Candle[]>(
    () => (dailyResp?.available ? (dailyResp.candles ?? []) : []),
    [dailyResp],
  );
  const gauges = useMemo(() => recommendations(dailyCandles), [dailyCandles]);

  const km = (data?.key_metrics?.available ? data.key_metrics.data : null) as Record<
    string,
    unknown
  > | null;

  const { data: overview } = useMarketOverview("nifty50");
  const indices = overview?.available ? overview.indices : [];
  const trending = overview?.available ? overview.most_active.slice(0, 6) : [];

  const streamLabel =
    streamStatus === "open" ? "live" : streamStatus === "reconnecting" ? "reconnecting" : "delayed";
  void now;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={`${data?.instrument.name ?? symbol}`}
        subtitle={`${exchange}:${symbol} · ${data?.instrument.instrument_type ?? "—"}`}
        actions={
          <span className="flex items-center gap-1.5 text-xs text-fg-faint">
            <span className={cn("h-1.5 w-1.5 rounded-full", streamStatus === "open" ? "bg-pos" : "bg-line-strong")} />
            {streamLabel}
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* ---- left column ---- */}
        <div className="flex flex-col gap-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-semibold tabular-nums">{num(q?.ltp)}</span>
                <span
                  className={cn("text-sm font-medium tabular-nums", chgPos ? "text-pos" : "text-neg")}
                >
                  {chgPos ? "+" : ""}
                  {num(q?.change)} ({chgPos ? "+" : ""}
                  {num(q?.change_pct)}%)
                </span>
              </div>
              {q && q.low != null && q.high != null && (
                <div className="mt-3">
                  <div className="flex justify-between text-[11px] text-fg-faint">
                    <span>{num(q.low)}</span>
                    <span>Day&apos;s range</span>
                    <span>{num(q.high)}</span>
                  </div>
                  <RangeBar low={q.low} high={q.high} value={q.ltp ?? q.low} />
                </div>
              )}
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                <Row k="Open" v={num(q?.open)} />
                <Row k="Prev close" v={num(q?.prev_close)} />
                <Row k="Volume" v={num(q?.volume, 0)} />
                <Row k="Avg price" v={num(q?.avg_price)} />
              </div>
              <div className="mt-3 flex gap-2 text-[11px] text-accent">
                <Link
                  to={`/charting?symbol=${encodeURIComponent(ref)}`}
                  className="flex items-center gap-1 rounded border border-line-strong px-2 py-1 hover:bg-elevated"
                >
                  <LineChartIcon className="h-3.5 w-3.5" /> Charting
                </Link>
                <Link
                  to={`/backtests?symbol=${encodeURIComponent(ref)}`}
                  className="flex items-center gap-1 rounded border border-line-strong px-2 py-1 hover:bg-elevated"
                >
                  <FlaskConical className="h-3.5 w-3.5" /> Backtest
                </Link>
                <Link
                  to="/alerts"
                  className="flex items-center gap-1 rounded border border-line-strong px-2 py-1 hover:bg-elevated"
                >
                  <Bell className="h-3.5 w-3.5" /> Alert
                </Link>
              </div>
            </CardContent>
          </Card>

          <SectionCard title="Investment recommendations">
            {gauges ? (
              <div className="grid grid-cols-3 gap-2">
                {gauges.map((g) => (
                  <Donut key={g.label} g={g} />
                ))}
              </div>
            ) : (
              <p className="py-6 text-center text-xs text-fg-faint">
                Not enough price history for a technical read.
              </p>
            )}
            {km && (
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 border-t border-line pt-3 text-xs">
                <Row k="Market cap" v={inrCompact(numericOr(km.marketCap ?? km.market_cap))} />
                <Row k="P/E" v={num(km.pe)} />
                <Row k="EPS" v={num(km.eps)} />
                <Row k="P/B" v={num(km.pb)} />
                <Row k="ROE" v={km.roe != null ? `${num(km.roe)}%` : "N/A"} />
                <Row k="Div yield" v={km.dividendYield != null || km.dividend_yield != null ? `${num(km.dividendYield ?? km.dividend_yield)}%` : "N/A"} />
                <Row k="52W high" v={num(km.week52High ?? km.high52)} />
                <Row k="52W low" v={num(km.week52Low ?? km.low52)} />
              </div>
            )}
          </SectionCard>
        </div>

        {/* ---- middle column: chart ---- */}
        <div className="xl:col-span-1">
          <SectionCard
            title={
              <span className="flex items-center gap-2">
                {symbol}
                <span className={cn("text-xs", chgPos ? "text-pos" : "text-neg")}>
                  {num(q?.ltp)} ({chgPos ? "+" : ""}
                  {num(q?.change_pct)}%)
                </span>
              </span>
            }
            actions={
              <span className="text-[11px] text-fg-faint">
                {candlesFetching ? "updating…" : "streaming"}
              </span>
            }
            bodyClassName="p-2"
          >
            <div className="mb-2 flex flex-wrap items-center gap-1 px-1">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTimeframe(tf)}
                  className={cn(
                    "rounded px-2 py-0.5 text-[11px] font-medium",
                    tf === timeframe ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
                  )}
                >
                  {tf}
                </button>
              ))}
            </div>
            {candles.length === 0 ? (
              <p className="py-16 text-center text-sm text-fg-faint">
                {candleResp && !candleResp.available
                  ? (candleResp as { reason?: string }).reason
                  : "Loading price history…"}
              </p>
            ) : (
              <PriceChart
                candles={candles}
                themeKey={`${theme}-${ref}-${timeframe}`}
                onReady={setChartApi as never}
                height={360}
              />
            )}
            <div className="mt-2 flex flex-wrap gap-1 px-1">
              {PERIODS.map((p, i) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => {
                    setPeriodIdx(i);
                    setTimeframe(p.tf);
                  }}
                  className={cn(
                    "rounded px-2 py-1 text-[11px] font-medium",
                    i === periodIdx
                      ? "bg-accent text-accent-fg"
                      : "border border-line-strong text-fg-muted hover:bg-elevated",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </SectionCard>
        </div>

        {/* ---- right column: quotes + trending ---- */}
        <div className="flex flex-col gap-4">
          <SectionCard title="Quotes">
            <div className="flex flex-col gap-1.5 text-xs">
              {indices.slice(0, 6).map((ix) => {
                const up = (ix.change_pct ?? 0) >= 0;
                return (
                  <div key={ix.symbol} className="flex items-center justify-between">
                    <span className="truncate text-fg-muted">{ix.name}</span>
                    <span className="flex items-center gap-3 tabular-nums">
                      <span>{ix.ltp?.toLocaleString("en-IN")}</span>
                      <span className={cn("w-16 text-right", up ? "text-pos" : "text-neg")}>
                        {up ? "+" : ""}
                        {ix.change_pct?.toFixed(2)}%
                      </span>
                    </span>
                  </div>
                );
              })}
              {indices.length === 0 && (
                <p className="py-4 text-center text-fg-faint">Live market data unavailable.</p>
              )}
            </div>
          </SectionCard>

          <SectionCard title="Trending stocks" bodyClassName="p-0">
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-fg-faint">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Company</th>
                  <th className="px-3 py-2 text-right font-medium">Price</th>
                  <th className="px-3 py-2 text-right font-medium">Chg</th>
                </tr>
              </thead>
              <tbody>
                {trending.map((s) => {
                  const up = (s.change_pct ?? 0) >= 0;
                  return (
                    <tr key={s.symbol} className="border-t border-line">
                      <td className="px-3 py-2 text-left">
                        <Link
                          to={`/stocks/NSE/${encodeURIComponent(s.symbol)}`}
                          className="font-medium text-fg hover:text-accent"
                        >
                          {s.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{num(s.ltp)}</td>
                      <td className={cn("px-3 py-2 text-right tabular-nums", up ? "text-pos" : "text-neg")}>
                        {up ? "+" : ""}
                        {s.change_pct?.toFixed(2)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <span className="text-fg-faint">{k}</span>
      <span className="tabular-nums">{v}</span>
    </div>
  );
}

function numericOr(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return isFinite(n) ? n : null;
}
