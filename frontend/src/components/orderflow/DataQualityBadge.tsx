import { useEffect, useRef, useState } from "react";

import type { Capabilities, DataTier } from "@/api/orderflow";
import { cn } from "@/lib/utils";

const TIER_META: Record<DataTier, { label: string; dot: string; text: string }> = {
  TRUE_ORDER_FLOW: { label: "TRUE ORDER FLOW", dot: "bg-pos", text: "text-pos" },
  ESTIMATED_ORDER_FLOW: { label: "ESTIMATED ORDER FLOW", dot: "bg-accent", text: "text-accent" },
  LIMITED_DATA: { label: "LIMITED DATA", dot: "bg-amber-500", text: "text-amber-500" },
  UNSUPPORTED: { label: "UNSUPPORTED", dot: "bg-neg", text: "text-neg" },
};

/** Click-to-expand data-quality pill. Shows the effective tier and, on
 *  click, exactly why the feed is or isn't sufficient for order flow. */
export function DataQualityBadge({
  live,
  historical,
  className,
}: {
  live?: Capabilities;
  historical?: Capabilities;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // The badge headline is the *weaker* of the two scopes in play.
  const order: DataTier[] = ["UNSUPPORTED", "LIMITED_DATA", "ESTIMATED_ORDER_FLOW", "TRUE_ORDER_FLOW"];
  const tiers = [historical?.tier, live?.tier].filter(Boolean) as DataTier[];
  const effective = tiers.sort((a, b) => order.indexOf(a) - order.indexOf(b))[0] ?? "LIMITED_DATA";
  const meta = TIER_META[effective];

  return (
    <div ref={ref} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded border border-line-strong bg-surface px-2 py-1 text-[11px] font-semibold tracking-wide",
          meta.text,
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
        {meta.label}
        <span className="text-fg-faint">▾</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-[22rem] max-w-[calc(100vw-2rem)] rounded-lg border border-line-strong bg-surface p-3 text-xs leading-relaxed shadow-xl">
          <p className="mb-2 text-fg-muted">
            Zerodha Kite provides ~1 snapshot/sec with cumulative volume and a 5-level
            depth ladder; the historical API is 1-minute OHLC. There is no
            trade-by-trade data with an aggressor side, so a true footprint / true
            delta / true CVD is <span className="font-semibold">not computed and not faked</span>.
          </p>
          {[historical, live].filter(Boolean).map((cap) => (
            <ScopeBlock key={cap!.scope} cap={cap!} />
          ))}
        </div>
      )}
    </div>
  );
}

function ScopeBlock({ cap }: { cap: Capabilities }) {
  const meta = TIER_META[cap.tier];
  return (
    <div className="mt-2 border-t border-line pt-2 first:mt-0 first:border-0 first:pt-0">
      <div className="flex items-center gap-1.5">
        <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
        <span className={cn("font-semibold", meta.text)}>{cap.scope.toUpperCase()}</span>
        <span className="text-fg-faint">— {meta.label}</span>
      </div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-fg-muted">
        {cap.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {cap.unsupported.length > 0 && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-fg-faint">Not supported on this feed</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-fg-faint">
            {cap.unsupported.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
