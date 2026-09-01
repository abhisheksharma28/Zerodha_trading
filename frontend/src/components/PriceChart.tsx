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

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const VISIBLE_BARS = 150;

function baseOptions(h: number) {
  const line = css("--color-line");
  return {
    height: h,
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--color-fg-faint"), fontSize: 11 },
    grid: { vertLines: { color: line }, horzLines: { color: line } },
    rightPriceScale: { borderColor: line, scaleMargins: { top: 0.08, bottom: 0.08 } },
    timeScale: {
      borderColor: line,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 6,
      barSpacing: 8,
      minBarSpacing: 1.5,
    },
    crosshair: { mode: CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    handleScale: {
      axisPressedMouseMove: { time: true, price: true },
      mouseWheel: true,
      pinch: true,
    },
    kineticScroll: { touch: true, mouse: false },
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
  onReady,
}: {
  candles: Candle[];
  overlays?: Overlay[];
  markers?: SeriesMarker<Time>[];
  subPanes?: SubPane[];
  themeKey?: string;
  height?: number;
  onHover?: (c: Candle | null) => void;
  onReady?: (
    api: { chart: IChartApi; series: ISeriesApi<"Candlestick">; container: HTMLDivElement } | null,
  ) => void;
}) {
  const mainRef = useRef<HTMLDivElement>(null);
  const subRefs = useRef<(HTMLDivElement | null)[]>([]);
  const charts = useRef<IChartApi[]>([]);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeries = useRef<Map<string, ISeriesApi<"Line" | "Histogram">>>(new Map());
  const subSeries = useRef<ISeriesApi<"Line" | "Histogram">[][]>([]);
  const candlesRef = useRef<Candle[]>(candles);
  const didInitialFit = useRef(false);

  candlesRef.current = candles;
  const panesKey = subPanes.map((p) => p.id).join("|");

  // Build the chart shell once per theme / symbol / pane-set — never per data tick.
  useEffect(() => {
    if (!mainRef.current) return;
    charts.current.forEach((c) => c.remove());
    charts.current = [];
    overlaySeries.current.clear();
    subSeries.current = [];
    didInitialFit.current = false;

    const main = createChart(mainRef.current, baseOptions(height));
    charts.current.push(main);
    candleSeries.current = main.addCandlestickSeries({
      upColor: css("--color-pos"),
      downColor: css("--color-neg"),
      borderVisible: false,
      wickUpColor: css("--color-pos"),
      wickDownColor: css("--color-neg"),
    });
    volSeries.current = main.addHistogramSeries({
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
    });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    if (onHover) {
      main.subscribeCrosshairMove((p) => {
        const t = p.time as number | undefined;
        onHover(t ? (candlesRef.current.find((c) => c.time === t) ?? null) : null);
      });
    }

    const subs: IChartApi[] = [];
    subPanes.forEach((_pane, i) => {
      const el = subRefs.current[i];
      if (!el) return;
      const sc = createChart(el, baseOptions(subPanes[i].height ?? 120));
      subs.push(sc);
      charts.current.push(sc);
      subSeries.current[i] = [];
    });

    let syncing = false;
    const all = [main, ...subs];
    all.forEach((src) =>
      src.timeScale().subscribeVisibleLogicalRangeChange((r) => {
        if (syncing || !r) return;
        syncing = true;
        all.forEach((d) => d !== src && d.timeScale().setVisibleLogicalRange(r));
        syncing = false;
      }),
    );

    if (onReady && candleSeries.current && mainRef.current) {
      onReady({ chart: main, series: candleSeries.current, container: mainRef.current });
    }

    return () => {
      onReady?.(null);
      charts.current.forEach((c) => c.remove());
      charts.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeKey, height, panesKey]);

  // Push data.
  useEffect(() => {
    const main = charts.current[0];
    if (!main || !candleSeries.current || candles.length === 0) return;

    candleSeries.current.setData(candles as never);
    candleSeries.current.setMarkers(markers);
    volSeries.current?.setData(
      candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open ? `${css("--color-pos")}44` : `${css("--color-neg")}44`,
      })),
    );

    const wanted = new Set(overlays.map((o) => o.id));
    for (const [id, s] of overlaySeries.current) {
      if (!wanted.has(id)) {
        main.removeSeries(s);
        overlaySeries.current.delete(id);
      }
    }
    for (const o of overlays) {
      let s = overlaySeries.current.get(o.id);
      if (!s) {
        s = main.addLineSeries({
          color: o.color,
          lineWidth: o.lineWidth ?? 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        overlaySeries.current.set(o.id, s);
      }
      s.applyOptions({ color: o.color });
      s.setData(o.data as never);
    }

    const subCharts = charts.current.slice(1);
    subPanes.forEach((pane, i) => {
      const sc = subCharts[i];
      if (!sc) return;
      (subSeries.current[i] ?? []).forEach((s) => sc.removeSeries(s));
      subSeries.current[i] = [];
      (pane.priceLines ?? []).forEach((v) => {
        const g = sc.addLineSeries({ color: css("--color-line-strong"), lineWidth: 1, lastValueVisible: false });
        g.setData(candles.map((c) => ({ time: c.time as Time, value: v })));
        subSeries.current[i].push(g);
      });
      pane.series.forEach((sd) => {
        const ser =
          sd.type === "histogram"
            ? sc.addHistogramSeries({ color: sd.color })
            : sc.addLineSeries({ color: sd.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
        ser.setData(sd.data as never);
        subSeries.current[i].push(ser);
      });
    });

    if (!didInitialFit.current) {
      const n = candles.length;
      main.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - VISIBLE_BARS), to: n + 4 });
      didInitialFit.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, overlays, markers, subPanes]);

  return (
    <div className="flex flex-col gap-1">
      <div ref={mainRef} className="w-full" style={{ height }} />
      {subPanes.map((p, i) => (
        <div key={p.id}>
          <p className="px-1 text-[10px] uppercase tracking-wide text-fg-faint">{p.label}</p>
          <div
            ref={(el) => {
              subRefs.current[i] = el;
            }}
            className="w-full"
            style={{ height: p.height ?? 120 }}
          />
        </div>
      ))}
    </div>
  );
}
