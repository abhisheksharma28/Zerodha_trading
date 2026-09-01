import { useEffect, useRef, useState } from "react";
import { Plus, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type IndicatorKind = "sma" | "ema" | "vwap" | "bbands" | "rsi" | "macd" | "atr";

export interface Indicator {
  uid: string;
  kind: IndicatorKind;
  period: number;
  color: string;
}

const CATALOG: { kind: IndicatorKind; label: string; group: string; period: number; hasPeriod: boolean }[] = [
  { kind: "sma", label: "SMA", group: "Trend", period: 20, hasPeriod: true },
  { kind: "ema", label: "EMA", group: "Trend", period: 20, hasPeriod: true },
  { kind: "vwap", label: "VWAP", group: "Trend", period: 0, hasPeriod: false },
  { kind: "bbands", label: "Bollinger Bands", group: "Volatility", period: 20, hasPeriod: true },
  { kind: "atr", label: "ATR", group: "Volatility", period: 14, hasPeriod: true },
  { kind: "rsi", label: "RSI", group: "Momentum", period: 14, hasPeriod: true },
  { kind: "macd", label: "MACD", group: "Momentum", period: 12, hasPeriod: false },
];

const PALETTE = ["#7c5cff", "#22b8cf", "#ffa94d", "#e64980", "#51cf66", "#fcc419"];

export function IndicatorMenu({
  value,
  onChange,
}: {
  value: Indicator[];
  onChange: (next: Indicator[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const add = (kind: IndicatorKind, period: number) => {
    const color = PALETTE[value.length % PALETTE.length];
    seq.current += 1;
    onChange([...value, { uid: `${kind}-${seq.current}`, kind, period, color }]);
  };
  const remove = (uid: string) => onChange(value.filter((i) => i.uid !== uid));
  const setPeriod = (uid: string, period: number) =>
    onChange(value.map((i) => (i.uid === uid ? { ...i, period } : i)));

  const groups = [...new Set(CATALOG.map((c) => c.group))];

  return (
    <div ref={ref} className="relative">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex h-8 items-center gap-1 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg-muted hover:bg-elevated hover:text-fg"
        >
          <Plus className="h-3.5 w-3.5" /> Indicators
        </button>
        {value.map((ind) => {
          const meta = CATALOG.find((c) => c.kind === ind.kind);
          return (
            <span
              key={ind.uid}
              className="flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs"
            >
              <span className="h-2 w-2 rounded-full" style={{ background: ind.color }} />
              <span className="text-fg">{meta?.label}</span>
              {meta?.hasPeriod && (
                <input
                  type="number"
                  value={ind.period}
                  onChange={(e) => setPeriod(ind.uid, Math.max(1, Number(e.target.value)))}
                  className="w-10 bg-transparent text-center text-fg-muted outline-none"
                />
              )}
              <button type="button" onClick={() => remove(ind.uid)} className="text-fg-faint hover:text-fg">
                <X className="h-3 w-3" />
              </button>
            </span>
          );
        })}
      </div>

      {open && (
        <div className="absolute z-30 mt-1 w-56 rounded-md border border-line-strong bg-surface p-2 shadow-xl">
          {groups.map((g) => (
            <div key={g} className="mb-1.5">
              <p className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                {g}
              </p>
              {CATALOG.filter((c) => c.group === g).map((c) => (
                <button
                  key={c.kind}
                  type="button"
                  onClick={() => {
                    add(c.kind, c.period);
                    setOpen(false);
                  }}
                  className={cn(
                    "block w-full rounded px-2 py-1 text-left text-sm text-fg-muted hover:bg-elevated hover:text-fg",
                  )}
                >
                  {c.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
