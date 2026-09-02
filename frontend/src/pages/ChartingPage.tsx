import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Time } from "lightweight-charts";

import { DrawingSurface, type ChartApi } from "@/components/DrawingLayer";
import { IndicatorMenu, type Indicator } from "@/components/IndicatorMenu";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { PageHeader } from "@/components/PageHeader";
import { PriceChart, type Overlay, type SubPane } from "@/components/PriceChart";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Card, CardContent } from "@/components/ui/card";
import { useCandles } from "@/hooks/useCandles";
import { useLiveTick } from "@/hooks/useLiveTick";
import { useNow } from "@/hooks/useNow";
import { atr, bollinger, ema, macd, rsi, sma, vwap, type Candle } from "@/lib/indicators";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

// Live ticks keep the last candle moving between polls; the REST poll only
// needs to reconcile the series (new bars, volume) reasonably often.
function refetchMsFor(timeframe: string): number {
  if (timeframe === "1d" || timeframe === "1w") return 60_000;
  return 10_000;
}

// Trailing history window. No cap — the backend pages large ranges from Kite.
const LOOKBACKS: { label: string; days?: number }[] = [
  { label: "1M", days: 31 },
  { label: "3M", days: 92 },
  { label: "6M", days: 183 },
  { label: "1Y", days: 365 },
  { label: "5Y", days: 1825 },
  { label: "10Y", days: 3650 },
  { label: "Max", days: 12000 },
  { label: "Default" }, // per-timeframe default
];

export default function ChartingPage() {
  const [params, setParams] = useSearchParams();
  const symbol = params.get("symbol") ?? "NSE:RELIANCE";
  const [timeframe, setTimeframe] = useState("15m");
  const [lookbackIdx, setLookbackIdx] = useState(LOOKBACKS.length - 1); // Default
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [hover, setHover] = useState<Candle | null>(null);
  const { theme } = useTheme();

  const drawKey = `${symbol}:${timeframe}`;
  const [chartApi, setChartApi] = useState<ChartApi | null>(null);

  const lookbackDays = LOOKBACKS[lookbackIdx].days;
  const { data, isLoading, isFetching, dataUpdatedAt } = useCandles(symbol, timeframe, {
    days: lookbackDays,
    // large historical windows don't need re-polling — the live tick keeps
    // the last candle moving; only short windows refresh the whole series.
    refetchMs: lookbackDays && lookbackDays > 400 ? undefined : refetchMsFor(timeframe),
  });
  const candles = useMemo<Candle[]>(
    () => (data?.available ? (data.candles ?? []) : []),
    [data],
  );
  const now = useNow(1000);
  const agoSecs = dataUpdatedAt ? Math.max(0, Math.round((now - dataUpdatedAt) / 1000)) : null;

  // --- live last-candle updates from the tick stream ---
  const { tick, status: streamStatus } = useLiveTick(symbol);
  const [liveLast, setLiveLast] = useState<Candle | null>(null);
  const lastTickAtRef = useRef(0);

  // A fresh REST payload is authoritative — drop the live overlay.
  useEffect(() => {
    setLiveLast(null);
  }, [candles]);

  useEffect(() => {
    if (!tick || tick.ltp == null || !chartApi || candles.length === 0) return;
    const base = liveLast ?? candles[candles.length - 1];
    const px = tick.ltp;
    const merged: Candle = {
      ...base,
      high: Math.max(base.high, px),
      low: Math.min(base.low, px),
      close: px,
    };
    lastTickAtRef.current = Date.now();
    setLiveLast(merged);
    chartApi.series.update({
      time: merged.time as Time,
      open: merged.open,
      high: merged.high,
      low: merged.low,
      close: merged.close,
    } as never);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, chartApi]);

  const tickFresh = now - lastTickAtRef.current < 6_000;
  const streamLive = streamStatus === "open" && tickFresh;

  const setSymbol = (s: string) => {
    params.set("symbol", s);
    setParams(params, { replace: true });
  };

  const { overlays, subPanes } = useMemo(() => {
    const ovs: Overlay[] = [];
    const panes: SubPane[] = [];
    if (candles.length === 0) return { overlays: ovs, subPanes: panes };
    for (const ind of indicators) {
      if (ind.kind === "sma") ovs.push({ id: ind.uid, data: sma(candles, ind.period), color: ind.color });
      else if (ind.kind === "ema") ovs.push({ id: ind.uid, data: ema(candles, ind.period), color: ind.color });
      else if (ind.kind === "vwap") ovs.push({ id: ind.uid, data: vwap(candles), color: ind.color });
      else if (ind.kind === "bbands") {
        const b = bollinger(candles, ind.period);
        ovs.push({ id: `${ind.uid}-u`, data: b.upper, color: ind.color, lineWidth: 1 });
        ovs.push({ id: `${ind.uid}-m`, data: b.middle, color: ind.color, lineWidth: 1 });
        ovs.push({ id: `${ind.uid}-l`, data: b.lower, color: ind.color, lineWidth: 1 });
      } else if (ind.kind === "atr") {
        panes.push({ id: ind.uid, label: `ATR ${ind.period}`, series: [{ id: "atr", type: "line", data: atr(candles, ind.period), color: ind.color }] });
      } else if (ind.kind === "rsi") {
        panes.push({
          id: ind.uid,
          label: `RSI ${ind.period}`,
          priceLines: [30, 70],
          series: [{ id: "rsi", type: "line", data: rsi(candles, ind.period), color: ind.color }],
        });
      } else if (ind.kind === "macd") {
        const m = macd(candles);
        panes.push({
          id: ind.uid,
          label: "MACD 12/26/9",
          height: 140,
          series: [
            { id: "hist", type: "histogram", data: m.hist, color: ind.color },
            { id: "macd", type: "line", data: m.macd, color: "#22b8cf" },
            { id: "signal", type: "line", data: m.signal, color: "#ffa94d" },
          ],
        });
      }
    }
    return { overlays: ovs, subPanes: panes };
  }, [candles, indicators]);

  const last = liveLast ?? candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const chg = last && prev ? ((last.close - prev.close) / prev.close) * 100 : null;
  const bar = hover ?? last;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Charting & Analysis"
        subtitle="Live candlesticks with indicators — real data from your Zerodha session."
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="w-72">
          <InstrumentSearch value={[symbol]} onChange={(v) => v[0] && setSymbol(v[0])} multiple={false} />
        </div>
        <TimeframeSelect value={timeframe} onChange={setTimeframe} />
        <IndicatorMenu value={indicators} onChange={setIndicators} />
        <div className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
          {LOOKBACKS.map((lb, i) => (
            <button
              key={lb.label}
              type="button"
              onClick={() => setLookbackIdx(i)}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium",
                i === lookbackIdx ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
              )}
            >
              {lb.label}
            </button>
          ))}
        </div>
      </div>

      <Card>
        <CardContent className="p-3">
          {isLoading ? (
            <p className="py-16 text-center text-sm text-fg-faint">Loading candles…</p>
          ) : data && !data.available ? (
            <div className="py-16 text-center">
              <p className="text-sm text-fg-muted">Chart data unavailable for {data.symbol}.</p>
              <p className="mx-auto mt-1 max-w-md text-xs text-fg-faint">{data.reason}</p>
            </div>
          ) : candles.length === 0 ? (
            <p className="py-16 text-center text-sm text-fg-faint">No candles returned.</p>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 px-1 text-sm">
                <span className="text-base font-semibold">{data?.symbol}</span>
                <span className="text-fg-muted">{timeframe}</span>
                {bar && (
                  <span className="flex gap-3 tabular-nums text-fg-muted">
                    <span>O {bar.open}</span>
                    <span>H {bar.high}</span>
                    <span>L {bar.low}</span>
                    <span className="text-fg">C {bar.close}</span>
                    <span>V {bar.volume.toLocaleString("en-IN")}</span>
                  </span>
                )}
                {chg != null && (
                  <span className={cn("font-medium tabular-nums", chg >= 0 ? "text-pos" : "text-neg")}>
                    {chg >= 0 ? "+" : ""}
                    {chg.toFixed(2)}%
                  </span>
                )}
                <span className="ml-auto flex items-center gap-1.5 text-xs text-fg-faint">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      streamLive
                        ? "bg-pos"
                        : streamStatus === "connecting" || streamStatus === "reconnecting"
                          ? "bg-accent animate-pulse"
                          : isFetching
                            ? "bg-accent"
                            : "bg-line-strong",
                    )}
                  />
                  {streamLive
                    ? "live · streaming"
                    : streamStatus === "reconnecting"
                      ? "reconnecting…"
                      : agoSecs == null || agoSecs <= 2
                        ? "live"
                        : `updated ${agoSecs}s ago`}
                </span>
              </div>
              <div className="relative">
                <PriceChart
                  candles={candles}
                  overlays={overlays}
                  subPanes={subPanes}
                  themeKey={`${theme}-${symbol}-${timeframe}`}
                  onHover={setHover}
                  onReady={setChartApi}
                  height={480}
                />
                <div
                  className="pointer-events-none absolute inset-x-0 top-0"
                  style={{ height: 480 }}
                >
                  <DrawingSurface key={drawKey} api={chartApi} storageKey={drawKey} />
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
