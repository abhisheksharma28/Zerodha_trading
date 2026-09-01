import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DrawingSurface, type ChartApi } from "@/components/DrawingLayer";
import { IndicatorMenu, type Indicator } from "@/components/IndicatorMenu";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { PageHeader } from "@/components/PageHeader";
import { PriceChart, type Overlay, type SubPane } from "@/components/PriceChart";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Card, CardContent } from "@/components/ui/card";
import { useCandles } from "@/hooks/useCandles";
import { atr, bollinger, ema, macd, rsi, sma, vwap, type Candle } from "@/lib/indicators";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export default function ChartingPage() {
  const [params, setParams] = useSearchParams();
  const symbol = params.get("symbol") ?? "NSE:RELIANCE";
  const [timeframe, setTimeframe] = useState("15m");
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [hover, setHover] = useState<Candle | null>(null);
  const { theme } = useTheme();

  const drawKey = `${symbol}:${timeframe}`;
  const [chartApi, setChartApi] = useState<ChartApi | null>(null);

  const { data, isLoading } = useCandles(symbol, timeframe);
  const candles = useMemo<Candle[]>(
    () => (data?.available ? (data.candles ?? []) : []),
    [data],
  );

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

  const last = candles[candles.length - 1];
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
                  <span className={cn("ml-auto font-medium tabular-nums", chg >= 0 ? "text-pos" : "text-neg")}>
                    {chg >= 0 ? "+" : ""}
                    {chg.toFixed(2)}%
                  </span>
                )}
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
