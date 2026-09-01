import { useEffect, useRef } from "react";
import {
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import type { Candle, LinePoint } from "@/lib/indicators";

export interface Overlay {
  id: string;
  data: LinePoint[];
  color: string;
  lineWidth?: 1 | 2 | 3 | 4;
}

export interface SubSeries {
  id: string;
  type: "line" | "histogram";
  data: LinePoint[];
  color: string;
}
export interface SubPane {
  id: string;
  label: string;
  series: SubSeries[];
  priceLines?: number[];
  height?: number;
}

function css(v: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(v).trim();
}

function chartTheme() {
  const line = css("--color-line");
  return {
    layout: { background: { color: "transparent" }, textColor: css("--color-fg-faint") },
    grid: { vertLines: { color: line }, horzLines: { color: line } },
    rightPriceScale: { borderColor: line },
    timeScale: { borderColor: line, timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
  };
}

export function PriceChart({
  candles,
  overlays = [],
  markers = [],
  subPanes = [],
  themeKey,
  height = 460,
  onHover,
}: {
  candles: Candle[];
  overlays?: Overlay[];
  markers?: SeriesMarker<Time>[];
  subPanes?: SubPane[];
  themeKey?: string;
  height?: number;
  onHover?: (c: Candle | null) => void;
}) {
  const mainRef = useRef<HTMLDivElement>(null);
  const subRefs = useRef<(HTMLDivElement | null)[]>([]);
  const apis = useRef<IChartApi[]>([]);

  // (re)build everything when data, overlays, panes or theme change
  useEffect(() => {
    if (!mainRef.current || candles.length === 0) return;
    apis.current.forEach((c) => c.remove());
    apis.current = [];

    const theme = chartTheme();
    const main = createChart(mainRef.current, {
      ...theme,
      autoSize: true,
      height,
    });
    apis.current.push(main);

    const candle = main.addCandlestickSeries({
      upColor: css("--color-pos"),
      downColor: css("--color-neg"),
      borderVisible: false,
      wickUpColor: css("--color-pos"),
      wickDownColor: css("--color-neg"),
    });
    candle.setData(candles as unknown as Parameters<typeof candle.setData>[0]);
    if (markers.length) candle.setMarkers(markers);

    const vol = main.addHistogramSeries({
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      color: css("--color-line-strong"),
    });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(
      candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? `${css("--color-pos")}55` : `${css("--color-neg")}55`,
      })),
    );

    const lineSeries: ISeriesApi<"Line">[] = [];
    for (const o of overlays) {
      const ls = main.addLineSeries({
        color: o.color,
        lineWidth: o.lineWidth ?? 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ls.setData(o.data as unknown as Parameters<typeof ls.setData>[0]);
      lineSeries.push(ls);
    }

    main.timeScale().fitContent();

    // crosshair -> OHLC readout
    if (onHover) {
      main.subscribeCrosshairMove((p) => {
        if (!p.time) return onHover(null);
        const c = candles.find((x) => x.time === (p.time as number));
        onHover(c ?? null);
      });
    }

    // sub panes (RSI / MACD) — separate charts, time-synced
    let syncing = false;
    const subs: IChartApi[] = [];
    subPanes.forEach((pane, i) => {
      const el = subRefs.current[i];
      if (!el) return;
      const sc = createChart(el, { ...theme, autoSize: true, height: pane.height ?? 120 });
      subs.push(sc);
      apis.current.push(sc);
      for (const s of pane.series) {
        const ser =
          s.type === "histogram"
            ? sc.addHistogramSeries({ color: s.color })
            : sc.addLineSeries({ color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
        ser.setData(s.data as unknown as Parameters<typeof ser.setData>[0]);
      }
      (pane.priceLines ?? []).forEach((v) => {
        const g = sc.addLineSeries({ color: css("--color-line-strong"), lineWidth: 1, lastValueVisible: false });
        g.setData(candles.map((c) => ({ time: c.time as Time, value: v })));
      });
      sc.timeScale().fitContent();
    });

    const allCharts = [main, ...subs];
    allCharts.forEach((src) => {
      src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        allCharts.forEach((dst) => {
          if (dst !== src) dst.timeScale().setVisibleLogicalRange(range);
        });
        syncing = false;
      });
    });

    return () => {
      apis.current.forEach((c) => c.remove());
      apis.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, overlays, markers, subPanes, themeKey, height]);

  return (
    <div className="flex flex-col gap-1">
      <div ref={mainRef} style={{ height }} />
      {subPanes.map((p, i) => (
        <div key={p.id}>
          <p className="px-1 text-[10px] uppercase tracking-wide text-fg-faint">{p.label}</p>
          <div
            ref={(el) => {
              subRefs.current[i] = el;
            }}
            style={{ height: p.height ?? 120 }}
          />
        </div>
      ))}
    </div>
  );
}
