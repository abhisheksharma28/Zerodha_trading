import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { RecommendationsPanel } from "@/components/scanner/RecommendationsPanel";
import { Card, CardContent } from "@/components/ui/card";
import { useLiveTicks } from "@/hooks/useLiveTick";
import { useMarketOverview } from "@/hooks/useMarket";
import { useStockDrawer } from "@/lib/stockDrawer";
import { cn } from "@/lib/utils";

const INDEX_OPTION_UNDERLYING: Record<string, string> = {
  "NIFTY 50": "NIFTY",
  "NIFTY BANK": "BANKNIFTY",
  "NIFTY FIN SERVICE": "FINNIFTY",
  "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
  "NIFTY NEXT 50": "NIFTYNXT50",
};

const pctClass = (p?: number | null) =>
  p == null ? "text-fg-muted" : p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-fg-muted";
const sign = (p?: number | null, d = 2) => (p == null ? "–" : `${p >= 0 ? "+" : ""}${p.toFixed(d)}%`);

function BreadthStrip({
  b,
}: {
  b: { advances: number; declines: number; unchanged: number; total: number; ad_ratio: number | null };
}) {
  const t = Math.max(b.total, 1);
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-xs">
      <span className="shrink-0 font-medium text-fg-muted">Breadth</span>
      <span className="tabular-nums text-pos">{b.advances}▲</span>
      <span className="tabular-nums text-fg-faint">{b.unchanged}=</span>
      <span className="tabular-nums text-neg">{b.declines}▼</span>
      <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-elevated">
        <div className="bg-pos" style={{ width: `${(b.advances / t) * 100}%` }} />
        <div className="bg-line-strong" style={{ width: `${(b.unchanged / t) * 100}%` }} />
        <div className="bg-neg" style={{ width: `${(b.declines / t) * 100}%` }} />
      </div>
      <span className="shrink-0 text-fg-muted">
        A/D <span className="font-medium tabular-nums text-fg">{b.ad_ratio ?? "–"}</span>
      </span>
      <Link to="/breadth" className="shrink-0 text-accent hover:underline">
        full breadth →
      </Link>
    </div>
  );
}

export default function MarketScannerPage() {
  const navigate = useNavigate();
  const { open: openDrawer } = useStockDrawer();
  const { data } = useMarketOverview("nifty50");

  const liveSymbols = useMemo(
    () => (data?.available ? data.indices.map((i) => `NSE:${i.symbol}`) : []),
    [data],
  );
  const { ticks } = useLiveTicks(liveSymbols);

  const openIndex = (sym: string) => {
    const u = INDEX_OPTION_UNDERLYING[sym.toUpperCase()];
    if (u) navigate(`/option-chain?underlying=${encodeURIComponent(u)}`);
    else openDrawer("NSE", sym);
  };

  if (data && !data.available) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Trade Ideas" subtitle="Full-market scan for the day's setups." />
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-sm text-fg-muted">Live market data unavailable.</p>
            <p className="mx-auto mt-1 max-w-md text-xs text-fg-faint">{data.reason}</p>
            <Link
              to="/broker"
              className="mt-3 inline-block rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:bg-accent-strong"
            >
              Connect Zerodha
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Trade Ideas"
        subtitle="Full-market scan — ranked, live-tracked setups. Market breadth is in the nav bar."
      />

      {!data ? (
        <p className="text-sm text-fg-faint">Loading…</p>
      ) : (
        <>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {data.indices.map((ix) => {
              const tick = ticks[`NSE:${ix.symbol}`];
              const ltp = tick?.ltp ?? ix.ltp;
              const chg =
                tick?.ltp != null && tick.ohlc?.close
                  ? ((tick.ltp - tick.ohlc.close) / tick.ohlc.close) * 100
                  : ix.change_pct;
              return (
                <button
                  key={ix.symbol}
                  type="button"
                  onClick={() => openIndex(ix.symbol)}
                  title={INDEX_OPTION_UNDERLYING[ix.symbol.toUpperCase()] ? "Open option chain" : "Open quote"}
                  className="min-w-[9rem] shrink-0 rounded-lg border border-line bg-surface px-3 py-2 text-left hover:border-line-strong"
                >
                  <p className="truncate text-[11px] text-fg-faint">{ix.name}</p>
                  <p className="mt-0.5 text-sm font-semibold tabular-nums">
                    {ltp?.toLocaleString("en-IN")}
                  </p>
                  <p className={cn("text-xs tabular-nums", pctClass(chg))}>{sign(chg)}</p>
                </button>
              );
            })}
          </div>

          <BreadthStrip b={data.breadth} />

          <RecommendationsPanel />
        </>
      )}
    </div>
  );
}
