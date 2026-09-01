import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Bell, FileText, FlaskConical, X } from "lucide-react";

import { stocksApi } from "@/api/stocks";
import { useCandles } from "@/hooks/useCandles";
import { atr, ema, rsi, sma, vwap, type Candle } from "@/lib/indicators";
import { useStockDrawer } from "@/lib/stockDrawer";
import { cn } from "@/lib/utils";

const TABS = ["Overview", "Technicals", "Fundamentals"] as const;

const num = (v: unknown, d = 2) =>
  typeof v === "number" && isFinite(v) ? v.toLocaleString("en-IN", { maximumFractionDigits: d }) : "N/A";

export function StockDrawer() {
  const { target, close } = useStockDrawer();
  if (!target) return null;
  return <Panel key={`${target.exchange}:${target.symbol}`} exchange={target.exchange} symbol={target.symbol} onClose={close} />;
}

function Panel({ exchange, symbol, onClose }: { exchange: string; symbol: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const ref = `${exchange}:${symbol}`;

  const { data, isLoading } = useQuery({
    queryKey: ["stock", exchange, symbol],
    queryFn: () => stocksApi.quickLook(exchange, symbol),
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });

  const q = data?.quote?.available ? data.quote : null;
  const chgPos = (q?.change_pct ?? 0) >= 0;

  const go = (path: string) => {
    onClose();
    navigate(path);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close" className="flex-1 bg-black/50" onClick={onClose} />
      <aside className="animate-in flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-line bg-surface shadow-2xl">
        {/* header */}
        <div className="sticky top-0 z-10 border-b border-line bg-surface px-4 pb-3 pt-4">
          <div className="flex items-start justify-between">
            <div className="min-w-0">
              <p className="truncate text-lg font-semibold">
                {data?.instrument.name ?? symbol}
              </p>
              <p className="text-xs text-fg-faint">
                {exchange}:{symbol} · {data?.instrument.instrument_type ?? data?.instrument.segment ?? "—"}
              </p>
            </div>
            <button type="button" onClick={onClose} className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg">
              <X className="h-4 w-4" />
            </button>
          </div>
          {q ? (
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="text-2xl font-semibold tabular-nums">{num(q.ltp)}</span>
              <span className={cn("text-sm font-medium tabular-nums", chgPos ? "text-pos" : "text-neg")}>
                {chgPos ? "+" : ""}
                {num(q.change)} ({chgPos ? "+" : ""}
                {num(q.change_pct)}%)
              </span>
            </div>
          ) : (
            <p className="mt-1.5 text-xs text-fg-faint">
              {isLoading ? "Loading quote…" : (data?.quote as { reason?: string })?.reason ?? "Quote unavailable"}
            </p>
          )}
        </div>

        {/* quick actions */}
        <div className="grid grid-cols-4 gap-1 border-b border-line px-3 py-3 text-center text-[11px] text-accent">
          <QuickAction icon={BarChart3} label="Chart" onClick={() => go(`/charting?symbol=${encodeURIComponent(ref)}`)} />
          <QuickAction icon={FlaskConical} label="Backtest" onClick={() => go(`/backtests?symbol=${encodeURIComponent(ref)}`)} />
          <QuickAction icon={Bell} label="Alert" onClick={() => go("/alerts")} />
          <QuickAction icon={FileText} label="Notes" onClick={() => go("/reports")} />
        </div>

        {/* day range */}
        {q && q.low != null && q.high != null && (
          <div className="border-b border-line px-4 py-3">
            <p className="mb-2 text-xs font-medium text-fg-muted">Day's range</p>
            <div className="flex justify-between text-xs">
              <span>
                <span className="text-fg-faint">Low </span>
                {num(q.low)}
              </span>
              <span>
                {num(q.high)}
                <span className="text-fg-faint"> High</span>
              </span>
            </div>
            <RangeBar low={q.low} high={q.high} value={q.ltp ?? q.low} />
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
              <Row k="Open" v={num(q.open)} />
              <Row k="Prev close" v={num(q.prev_close)} />
              <Row k="Volume" v={num(q.volume, 0)} />
              <Row k="Avg price" v={num(q.avg_price)} />
              {q.upper_circuit != null && <Row k="Upper circuit" v={num(q.upper_circuit)} />}
              {q.lower_circuit != null && <Row k="Lower circuit" v={num(q.lower_circuit)} />}
            </div>
            {q.depth && (q.depth.buy.some((b) => b.quantity) || q.depth.sell.some((s) => s.quantity)) && (
              <MarketDepth
                buy={q.depth.buy}
                sell={q.depth.sell}
                totalBuy={q.buy_quantity}
                totalSell={q.sell_quantity}
              />
            )}
          </div>
        )}

        {/* tabs */}
        <div className="flex gap-1 border-b border-line px-3">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-2 text-xs font-medium",
                t === tab ? "border-b-2 border-accent text-fg" : "text-fg-muted hover:text-fg",
              )}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="flex-1 p-4">
          {tab === "Overview" && <OverviewTab data={data} />}
          {tab === "Technicals" && <TechnicalsTab ref_={ref} />}
          {tab === "Fundamentals" && <FundamentalsTab exchange={exchange} symbol={symbol} />}
        </div>
      </aside>
    </div>
  );
}

function QuickAction({ icon: Icon, label, onClick }: { icon: typeof Bell; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex flex-col items-center gap-1 rounded-md py-1.5 hover:bg-elevated">
      <Icon className="h-4 w-4" />
      {label}
    </button>
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

type Lvl = { price: number; quantity: number; orders: number };
function MarketDepth({
  buy,
  sell,
  totalBuy,
  totalSell,
}: {
  buy: Lvl[];
  sell: Lvl[];
  totalBuy: number | null;
  totalSell: number | null;
}) {
  const max = Math.max(1, ...buy.map((b) => b.quantity), ...sell.map((s) => s.quantity));
  const rows = Math.max(buy.length, sell.length, 5);
  return (
    <div className="mt-3">
      <p className="mb-1 text-[11px] font-medium text-fg-muted">Market depth</p>
      <div className="grid grid-cols-2 gap-2 text-[11px] tabular-nums">
        <div>
          <div className="mb-0.5 flex justify-between text-fg-faint">
            <span>Qty</span>
            <span>Bid</span>
          </div>
          {Array.from({ length: rows }).map((_, i) => {
            const b = buy[i];
            return (
              <div key={i} className="relative flex justify-between px-1 py-0.5">
                {b && (
                  <span
                    className="absolute inset-y-0 right-0 bg-pos/15"
                    style={{ width: `${(b.quantity / max) * 100}%` }}
                  />
                )}
                <span className="relative">{b ? num(b.quantity, 0) : "–"}</span>
                <span className="relative text-pos">{b ? num(b.price) : ""}</span>
              </div>
            );
          })}
        </div>
        <div>
          <div className="mb-0.5 flex justify-between text-fg-faint">
            <span>Ask</span>
            <span>Qty</span>
          </div>
          {Array.from({ length: rows }).map((_, i) => {
            const s = sell[i];
            return (
              <div key={i} className="relative flex justify-between px-1 py-0.5">
                {s && (
                  <span
                    className="absolute inset-y-0 left-0 bg-neg/15"
                    style={{ width: `${(s.quantity / max) * 100}%` }}
                  />
                )}
                <span className="relative text-neg">{s ? num(s.price) : ""}</span>
                <span className="relative">{s ? num(s.quantity, 0) : "–"}</span>
              </div>
            );
          })}
        </div>
      </div>
      {(totalBuy != null || totalSell != null) && (
        <div className="mt-1 flex justify-between text-[11px] text-fg-faint">
          <span>Total bid {num(totalBuy, 0)}</span>
          <span>Total ask {num(totalSell, 0)}</span>
        </div>
      )}
    </div>
  );
}

function RangeBar({ low, high, value }: { low: number; high: number; value: number }) {
  const pct = high > low ? Math.min(100, Math.max(0, ((value - low) / (high - low)) * 100)) : 50;
  return (
    <div className="relative mt-1.5 h-1.5 w-full rounded-full bg-elevated">
      <div className="absolute h-full rounded-full bg-accent/60" style={{ width: `${pct}%` }} />
      <div className="absolute -top-1 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-surface bg-accent" style={{ left: `${pct}%` }} />
    </div>
  );
}

function OverviewTab({ data }: { data?: import("@/api/stocks").StockQuickLook }) {
  const km = (data?.key_metrics?.available ? data.key_metrics.data : null) as Record<string, unknown> | null;
  const inst = data?.instrument;
  return (
    <div className="flex flex-col gap-4">
      {km ? (
        <div className="grid grid-cols-2 gap-3">
          {[
            ["Market cap", km.marketCap ?? km.market_cap],
            ["P/E", km.pe],
            ["P/B", km.pb],
            ["ROE", km.roe],
            ["ROCE", km.roce],
            ["Div yield", km.dividendYield ?? km.dividend_yield],
            ["Debt/Equity", km.debtToEquity ?? km.debt_equity],
            ["EPS", km.eps],
            ["52W high", km.week52High ?? km.high52],
            ["52W low", km.week52Low ?? km.low52],
            ["Beta", km.beta],
          ].map(([label, v]) => (
            <div key={label as string} className="rounded-md border border-line bg-bg p-2.5">
              <p className="text-[11px] uppercase tracking-wide text-fg-faint">{label as string}</p>
              <p className="mt-0.5 text-sm font-semibold tabular-nums">{num(v)}</p>
            </div>
          ))}
        </div>
      ) : (
        <ProviderNote reason={data?.profile?.reason} />
      )}
      {inst && (
        <div className="rounded-md border border-line bg-bg p-3 text-xs">
          <p className="mb-1.5 font-medium text-fg-muted">Instrument</p>
          <Row k="Token" v={inst.instrument_token} />
          <Row k="Segment" v={inst.segment ?? "—"} />
          <Row k="Lot size" v={inst.lot_size ?? "—"} />
          <Row k="Tick size" v={inst.tick_size ?? "—"} />
        </div>
      )}
    </div>
  );
}

function interpret(price: number, e20?: number, e50?: number, r?: number) {
  let trend = "NEUTRAL";
  if (e20 && e50) trend = price > e20 && e20 > e50 ? "BULLISH" : price < e20 && e20 < e50 ? "BEARISH" : "NEUTRAL";
  const momentum = r == null ? "—" : r >= 60 ? "STRONG" : r <= 40 ? "WEAK" : "NEUTRAL";
  return { trend, momentum };
}

function TechnicalsTab({ ref_ }: { ref_: string }) {
  const { data } = useCandles(ref_, "1d", 260);
  const candles = useMemo<Candle[]>(() => (data?.available ? (data.candles ?? []) : []), [data]);

  const t = useMemo(() => {
    if (candles.length < 60) return null;
    const price = candles[candles.length - 1].close;
    const last = (a: { value: number }[]) => (a.length ? a[a.length - 1].value : undefined);
    const e20 = last(ema(candles, 20));
    const e50 = last(ema(candles, 50));
    const e200 = last(ema(candles, 200));
    const s20 = last(sma(candles, 20));
    const rv = last(rsi(candles, 14));
    const av = last(atr(candles, 14));
    const vw = last(vwap(candles));
    const vols = candles.slice(-20).map((c) => c.volume);
    const relVol = vols.length ? candles[candles.length - 1].volume / (vols.reduce((a, b) => a + b, 0) / vols.length) : undefined;
    return { price, e20, e50, e200, s20, rv, av, vw, relVol, ...interpret(price, e20, e50, rv) };
  }, [candles]);

  if (!data) return <p className="text-xs text-fg-faint">Loading price history…</p>;
  if (!data.available) return <p className="text-xs text-fg-faint">{(data as { reason?: string }).reason}</p>;
  if (!t) return <p className="text-xs text-fg-faint">Not enough history for technicals.</p>;

  const rows: [string, unknown][] = [
    ["Price", t.price],
    ["EMA 20", t.e20],
    ["EMA 50", t.e50],
    ["EMA 200", t.e200],
    ["SMA 20", t.s20],
    ["VWAP", t.vw],
    ["RSI (14)", t.rv],
    ["ATR (14)", t.av],
    ["Rel. volume", t.relVol],
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2 text-[11px]">
        <Tag label={`Trend: ${t.trend}`} tone={t.trend === "BULLISH" ? "pos" : t.trend === "BEARISH" ? "neg" : "muted"} />
        <Tag label={`Momentum: ${t.momentum}`} tone={t.momentum === "STRONG" ? "pos" : t.momentum === "WEAK" ? "neg" : "muted"} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {rows.map(([k, v]) => (
          <div key={k} className="rounded-md border border-line bg-bg p-2.5">
            <p className="text-[11px] uppercase tracking-wide text-fg-faint">{k}</p>
            <p className="mt-0.5 text-sm font-semibold tabular-nums">{num(v)}</p>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-fg-faint">
        Analytical only — computed from daily candles, not financial advice.
      </p>
    </div>
  );
}

function FundamentalsTab({ exchange, symbol }: { exchange: string; symbol: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["stock", "fundamentals", exchange, symbol],
    queryFn: () => stocksApi.fundamentals(exchange, symbol),
    staleTime: 6 * 60 * 60_000,
  });
  if (isLoading) return <p className="text-xs text-fg-faint">Loading…</p>;
  if (!data) return <p className="text-xs text-fg-faint">Unavailable.</p>;
  if (data.provider === "none") return <ProviderNote reason={data.profile.reason} />;

  const sections: [string, import("@/api/stocks").ProviderResult][] = [
    ["Company profile", data.profile],
    ["Key metrics", data.key_metrics],
    ["Income statement", data.income_statement],
    ["Quarterly results", data.quarterly_results],
    ["Balance sheet", data.balance_sheet],
    ["Cash flow", data.cash_flow],
    ["Shareholding", data.shareholding],
    ["Corporate actions", data.corporate_actions],
    ["News", data.news],
  ];
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] text-fg-faint">Source: {data.provider}</p>
      {sections.map(([label, r]) => (
        <details key={label} className="rounded-md border border-line bg-bg p-2.5 text-xs">
          <summary className="cursor-pointer font-medium">
            {label} {!r.available && <span className="text-fg-faint">· {r.reason}</span>}
          </summary>
          {r.available && (
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-fg-muted">
              {JSON.stringify(r.data, null, 2)}
            </pre>
          )}
        </details>
      ))}
    </div>
  );
}

function ProviderNote({ reason }: { reason?: string | null }) {
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-300">
      <p className="font-medium">Fundamentals data provider not configured</p>
      <p className="mt-1 text-amber-200/80">{reason}</p>
      <p className="mt-2 text-amber-200/70">
        Set <code>FUNDAMENTALS_PROVIDER</code> in the backend env (e.g. <code>indianapi</code> with a key).
        The adapter interface lives in <code>app/providers/fundamentals</code>.
      </p>
    </div>
  );
}

function Tag({ label, tone }: { label: string; tone: "pos" | "neg" | "muted" }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 font-medium",
        tone === "pos" ? "bg-pos/10 text-pos" : tone === "neg" ? "bg-neg/10 text-neg" : "bg-elevated text-fg-muted",
      )}
    >
      {label}
    </span>
  );
}
