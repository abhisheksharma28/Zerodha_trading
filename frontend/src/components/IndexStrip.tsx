import { useNavigate } from "react-router-dom";

import { useLiveTicks } from "@/hooks/useLiveTick";
import { useMarketOverview } from "@/hooks/useMarket";
import { cn } from "@/lib/utils";

// Persistent NIFTY 50 / BANK NIFTY ticker shown under the nav on every tab.
const WATCH: { label: string; index: string; underlying: string }[] = [
  { label: "NIFTY 50", index: "NIFTY 50", underlying: "NIFTY" },
  { label: "BANK NIFTY", index: "NIFTY BANK", underlying: "BANKNIFTY" },
  { label: "FIN NIFTY", index: "NIFTY FIN SERVICE", underlying: "FINNIFTY" },
  { label: "INDIA VIX", index: "INDIA VIX", underlying: "" },
];

const fmt = (v: number | null | undefined) =>
  v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export function IndexStrip() {
  const navigate = useNavigate();
  const { data } = useMarketOverview("nifty50");
  const { ticks } = useLiveTicks(WATCH.map((w) => `NSE:${w.index}`));

  if (!data?.available) return null;

  const rows = WATCH.map((w) => {
    const base = data.indices.find((i) => i.symbol.toUpperCase() === w.index.toUpperCase());
    if (!base) return null;
    const t = ticks[`NSE:${w.index}`];
    const ltp = t?.ltp ?? base.ltp ?? null;
    const prev = base.prev_close ?? (base.ltp != null && base.change_pct != null
      ? base.ltp / (1 + base.change_pct / 100)
      : null);
    const changePct = prev && ltp != null ? ((ltp - prev) / prev) * 100 : base.change_pct;
    return { ...w, ltp, changePct };
  }).filter(Boolean) as { label: string; underlying: string; ltp: number | null; changePct: number | null }[];

  if (rows.length === 0) return null;

  return (
    <div className="sticky top-14 z-30 border-b border-line bg-surface/80 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] items-center gap-5 overflow-x-auto px-4 py-1.5 text-xs">
        {rows.map((r) => {
          const up = (r.changePct ?? 0) >= 0;
          const clickable = !!r.underlying;
          return (
            <button
              key={r.label}
              type="button"
              disabled={!clickable}
              onClick={() =>
                clickable && navigate(`/option-chain?underlying=${encodeURIComponent(r.underlying)}`)
              }
              className={cn(
                "flex shrink-0 items-center gap-1.5 tabular-nums",
                clickable && "hover:text-accent",
              )}
              title={clickable ? "Open option chain" : undefined}
            >
              <span className="font-medium text-fg-muted">{r.label}</span>
              <span className="text-fg">{fmt(r.ltp)}</span>
              <span className={cn(up ? "text-pos" : "text-neg")}>
                {up ? "▲" : "▼"} {r.changePct == null ? "–" : `${Math.abs(r.changePct).toFixed(2)}%`}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
