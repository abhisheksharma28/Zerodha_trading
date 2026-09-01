import { useCallback, useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { Minus, MousePointer2, Ruler, Slash, Square, Trash2, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";

export type ChartApi = {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  container: HTMLDivElement;
};
type Tool = "cursor" | "trend" | "hline" | "ray" | "rect" | "fib";
interface Pt {
  time: number;
  price: number;
}
interface Drawing {
  id: string;
  tool: Exclude<Tool, "cursor">;
  a: Pt;
  b: Pt;
}

const FIBS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const TOOLS: { tool: Tool; icon: typeof Minus; label: string }[] = [
  { tool: "cursor", icon: MousePointer2, label: "Cursor" },
  { tool: "trend", icon: TrendingUp, label: "Trend line" },
  { tool: "hline", icon: Minus, label: "Horizontal line" },
  { tool: "ray", icon: Slash, label: "Ray" },
  { tool: "rect", icon: Square, label: "Rectangle" },
  { tool: "fib", icon: Ruler, label: "Fib retracement" },
];

function load(key: string): Drawing[] {
  try {
    return JSON.parse(localStorage.getItem(`chart-drawings:${key}`) ?? "[]") as Drawing[];
  } catch {
    return [];
  }
}
function persist(key: string, d: Drawing[]) {
  try {
    localStorage.setItem(`chart-drawings:${key}`, JSON.stringify(d));
  } catch {
    /* ignore */
  }
}

/** Floating toolbar + SVG drawing overlay for a lightweight-charts pane.
 *  Self-contained: give it a React `key` (symbol:timeframe) to reset. */
export function DrawingSurface({ api, storageKey }: { api: ChartApi | null; storageKey: string }) {
  const [tool, setTool] = useState<Tool>("cursor");
  const [drawings, setDrawings] = useState<Drawing[]>(() => load(storageKey));
  const [draft, setDraft] = useState<{ a: Pt; b: Pt } | null>(null);
  const [, bump] = useState(0);
  const seq = useRef(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const reproject = useCallback(() => bump((n) => n + 1), []);

  useEffect(() => {
    if (!api) return;
    const ts = api.chart.timeScale();
    ts.subscribeVisibleTimeRangeChange(reproject);
    const ro = new ResizeObserver(reproject);
    ro.observe(api.container);
    const raf = requestAnimationFrame(reproject);
    return () => {
      ts.unsubscribeVisibleTimeRangeChange(reproject);
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [api, reproject]);

  const toXY = (p: Pt) => {
    if (!api) return null;
    const x = api.chart.timeScale().timeToCoordinate(p.time as Time);
    const y = api.series.priceToCoordinate(p.price);
    return x == null || y == null ? null : { x: x as number, y: y as number };
  };
  const fromEvent = (e: React.PointerEvent): Pt | null => {
    if (!api || !svgRef.current) return null;
    const r = svgRef.current.getBoundingClientRect();
    const time = api.chart.timeScale().coordinateToTime(e.clientX - r.left);
    const price = api.series.coordinateToPrice(e.clientY - r.top);
    return time == null || price == null ? null : { time: time as number, price };
  };

  const onDown = (e: React.PointerEvent) => {
    if (tool === "cursor") return;
    const p = fromEvent(e);
    if (!p) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDraft({ a: p, b: p });
  };
  const onMove = (e: React.PointerEvent) => {
    if (!draft) return;
    const p = fromEvent(e);
    if (p) setDraft((d) => (d ? { ...d, b: p } : d));
  };
  const onUp = () => {
    if (!draft) {
      return;
    }
    const { a, b } = draft;
    setDraft(null);
    if (tool === "cursor") return;
    seq.current += 1;
    const next: Drawing = {
      id: `${tool}-${seq.current}`,
      tool,
      a,
      b: tool === "hline" ? { time: b.time, price: a.price } : b,
    };
    setDrawings((list) => {
      const updated = [...list, next];
      persist(storageKey, updated);
      return updated;
    });
    setTool("cursor");
  };

  const clear = () => {
    setDrawings([]);
    persist(storageKey, []);
  };

  const stroke = "var(--color-accent)";
  const renderOne = (d: { tool: Tool; a: Pt; b: Pt }, key: string) => {
    const A = toXY(d.a);
    const B = toXY(d.b);
    if (!A || !B) return null;
    if (d.tool === "hline") {
      return <line key={key} x1={0} x2="100%" y1={A.y} y2={A.y} stroke={stroke} strokeWidth={1} strokeDasharray="4 3" />;
    }
    if (d.tool === "rect") {
      return (
        <rect
          key={key}
          x={Math.min(A.x, B.x)}
          y={Math.min(A.y, B.y)}
          width={Math.abs(B.x - A.x)}
          height={Math.abs(B.y - A.y)}
          fill="var(--color-accent-soft)"
          stroke={stroke}
          strokeWidth={1}
        />
      );
    }
    if (d.tool === "fib") {
      const lo = Math.min(d.a.price, d.b.price);
      const hi = Math.max(d.a.price, d.b.price);
      return (
        <g key={key}>
          {FIBS.map((f) => {
            const y = api?.series.priceToCoordinate(hi - f * (hi - lo));
            if (y == null) return null;
            return (
              <g key={f}>
                <line x1={Math.min(A.x, B.x)} x2={Math.max(A.x, B.x)} y1={y} y2={y} stroke={stroke} strokeWidth={0.75} strokeOpacity={0.7} />
                <text x={Math.max(A.x, B.x) + 3} y={(y as number) + 3} fontSize={9} fill="var(--color-fg-faint)">
                  {f} · {(hi - f * (hi - lo)).toFixed(1)}
                </text>
              </g>
            );
          })}
        </g>
      );
    }
    let x2 = B.x;
    let y2 = B.y;
    if (d.tool === "ray" && B.x !== A.x) {
      const slope = (B.y - A.y) / (B.x - A.x);
      x2 = B.x > A.x ? 4000 : -4000;
      y2 = A.y + slope * (x2 - A.x);
    }
    return <line key={key} x1={A.x} y1={A.y} x2={x2} y2={y2} stroke={stroke} strokeWidth={1.25} />;
  };

  return (
    <>
      <div className="absolute left-2 top-2 z-20 inline-flex items-center gap-0.5 rounded-md border border-line-strong bg-surface/95 p-0.5 shadow-lg">
        {TOOLS.map(({ tool: t, icon: Icon, label }) => (
          <button
            key={t}
            type="button"
            title={label}
            onClick={() => setTool(t)}
            className={cn(
              "rounded p-1.5",
              tool === t ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-elevated hover:text-fg",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        ))}
        <span className="mx-0.5 h-4 w-px bg-line" />
        <button
          type="button"
          title="Clear drawings"
          onClick={clear}
          disabled={drawings.length === 0}
          className="rounded p-1.5 text-fg-muted hover:bg-elevated hover:text-neg disabled:opacity-40"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <svg
        ref={svgRef}
        className={cn("absolute inset-0 h-full w-full", tool === "cursor" ? "pointer-events-none" : "cursor-crosshair")}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        {drawings.map((d) => renderOne(d, d.id))}
        {draft && renderOne({ tool, ...draft }, "draft")}
      </svg>
    </>
  );
}

