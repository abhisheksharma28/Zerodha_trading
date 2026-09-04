import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RefreshCw } from "lucide-react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Card, CardContent } from "@/components/ui/card";
import { useLiveTicks } from "@/hooks/useLiveTick";
import { useMarketOverview } from "@/hooks/useMarket";
import { useNow } from "@/hooks/useNow";
import type { LiveTick } from "@/lib/marketStream";
import { useStockDrawer } from "@/lib/stockDrawer";
import type { MarketIndexRow, MarketQuoteRow, SectorRow } from "@/types/api";
import { countCompact, inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = ["Movers", "Sectors", "Heat-map", "Signals", "Most Active"] as const;

// Index tradingsymbol → F&O underlying for the option chain. Only indices that
// actually trade options are listed; anything else opens the quote drawer.
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
const fmtVol = (v?: number | null) => countCompact(v);
const heatStyle = (p: number): React.CSSProperties => {
  const t = Math.max(-3, Math.min(3, p)) / 3;
  const a = 0.12 + 0.5 * Math.abs(t);
  return { backgroundColor: t >= 0 ? `rgba(52,211,153,${a})` : `rgba(248,113,113,${a})` };
};

function useSym() {
  const { open } = useStockDrawer();
  return (sym: string) => open("NSE", sym);
}

function SymLink({ sym }: { sym: string }) {
  const openStock = useSym();
  return (
    <button
      type="button"
      onClick={() => openStock(sym)}
      className="font-medium text-fg hover:text-accent hover:underline"
    >
      {sym}
    </button>
  );
}

// Prev close for a tick: Kite's OHLC "close" is the previous day's close
// during the session; fall back to implying it from the REST snapshot.
function prevCloseOf(row: MarketQuoteRow, tick: LiveTick): number | null {
  if (tick.ohlc?.close) return tick.ohlc.close;
  if (row.ltp != null && row.change_pct != null && 1 + row.change_pct / 100 !== 0) {
    return row.ltp / (1 + row.change_pct / 100);
  }
  return null;
}

// Overlay a live tick onto a REST snapshot row.
function withLiveRow<T extends MarketQuoteRow>(row: T, tick?: LiveTick): T {
  if (!tick || tick.ltp == null) return row;
  const ltp = tick.ltp;
  const pc = prevCloseOf(row, tick);
  const volume = tick.volume ?? row.volume;
  return {
    ...row,
    ltp,
    change: pc != null ? ltp - pc : row.change,
    change_pct: pc ? ((ltp - pc) / pc) * 100 : row.change_pct,
    volume,
    value: volume != null ? ltp * volume : row.value,
  };
}

export default function BreadthPage() {
  const openStock = useSym();
  const navigate = useNavigate();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Movers");
  const [universe, setUniverse] = useState<"nifty50" | "nifty100" | "nifty200">("nifty200");
  const { data, isFetching, refetch, dataUpdatedAt } = useMarketOverview(universe);

  const liveSymbols = useMemo(() => {
    if (!data?.available) return [];
    return [
      ...data.heatmap.map((h) => `NSE:${h.symbol}`),
      ...data.indices.map((i) => `NSE:${i.symbol}`),
    ];
  }, [data]);
  const { ticks: liveTicks, status: streamStatus } = useLiveTicks(liveSymbols);
  const live = (sym: string) => liveTicks[`NSE:${sym}`];

  const openIndex = (sym: string) => {
    const underlying = INDEX_OPTION_UNDERLYING[sym.toUpperCase()];
    if (underlying) navigate(`/option-chain?underlying=${encodeURIComponent(underlying)}`);
    else openStock(sym);
  };

  const stockCols: Column<MarketQuoteRow>[] = useMemo(
    () => [
      {
        key: "sym",
        header: "Symbol",
        cell: (s) => <SymLink sym={s.symbol} />,
        sortValue: (s) => s.symbol,
      },
      {
        key: "ltp",
        header: "LTP",
        align: "right",
        cell: (s) => num(s.ltp),
        sortValue: (s) => s.ltp,
      },
      {
        key: "chg",
        header: "Chg %",
        align: "right",
        cell: (s) => <span className={pctClass(s.change_pct)}>{sign(s.change_pct)}</span>,
        sortValue: (s) => s.change_pct,
      },
      {
        key: "vol",
        header: "Volume",
        align: "right",
        cell: (s) => fmtVol(s.volume),
        sortValue: (s) => s.volume,
      },
    ],
    [],
  );

  const view = useMemo(() => {
    if (!data?.available) return null;
    const rows = (rs: MarketQuoteRow[]) => rs.map((r) => withLiveRow(r, live(r.symbol)));
    const gainersAll = rows(data.gainers);
    const losersAll = rows(data.losers);
    return {
      indices: data.indices.map((i) => withLiveRow(i, live(i.symbol))) as MarketIndexRow[],
      gainers: [...gainersAll].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)),
      losers: [...losersAll].sort((a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0)),
      most_active: [...rows(data.most_active)].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)),
      heatmap: data.heatmap.map((h) => {
        const t = live(h.symbol);
        if (!t || t.ltp == null || !t.ohlc?.close) return h;
        return { ...h, change_pct: ((t.ltp - t.ohlc.close) / t.ohlc.close) * 100 };
      }),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, liveTicks]);

  if (data && !data.available) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Market Breadth" subtitle="Live NSE movers, sectors, heat-map and signals." />
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-sm text-fg-muted">Live market data unavailable.</p>
            <p className="mx-auto mt-1 max-w-md text-xs text-fg-faint">{data.reason}</p>
            <Link to="/broker" className="mt-3 inline-block rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:bg-accent-strong">
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
        title="Market Breadth"
        subtitle="Live NSE movers, sectors, heat-map and signals — real Zerodha quotes."
        actions={
          <div className="flex items-center gap-2">
            <select
              className="h-8 rounded-md border border-line bg-surface px-2 text-xs"
              value={universe}
              onChange={(e) => setUniverse(e.target.value as typeof universe)}
              title="Which basket of stocks the movers / breadth are computed over"
            >
              <option value="nifty50">Nifty 50</option>
              <option value="nifty100">Nifty 100</option>
              <option value="nifty200">Nifty 200</option>
            </select>
            {streamStatus === "open" && (
              <span className="hidden items-center gap-1 text-xs font-medium text-pos sm:flex">
                <span className="h-1.5 w-1.5 rounded-full bg-pos" /> streaming
              </span>
            )}
            <LiveClock updatedAt={dataUpdatedAt} fetching={isFetching} onRefresh={refetch} />
          </div>
        }
      />

      {!data ? (
        <p className="text-sm text-fg-faint">Loading market data…</p>
      ) : (
        <>
          {/* index strip */}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {(view ?? data).indices.map((ix) => (
              <button
                key={ix.symbol}
                type="button"
                onClick={() => openIndex(ix.symbol)}
                title={
                  INDEX_OPTION_UNDERLYING[ix.symbol.toUpperCase()]
                    ? "Open option chain"
                    : "Open quote"
                }
                className="min-w-[9rem] shrink-0 rounded-lg border border-line bg-surface px-3 py-2 text-left hover:border-line-strong"
              >
                <p className="truncate text-[11px] text-fg-faint">{ix.name}</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums">{ix.ltp?.toLocaleString("en-IN")}</p>
                <p className={cn("text-xs tabular-nums", pctClass(ix.change_pct))}>{sign(ix.change_pct)}</p>
              </button>
            ))}
          </div>

          {/* slim breadth strip */}
          <BreadthStrip b={data.breadth} />

          {/* tabs */}
          <div className="flex gap-1 border-b border-line">
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

          {tab === "Movers" && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <SectionCard title="Gainers" bodyClassName="p-0">
                <DataTable
                  columns={stockCols}
                  rows={(view ?? data).gainers}
                  rowKey={(s) => s.symbol}
                  searchable
                  searchPlaceholder="Filter gainers…"
                />
              </SectionCard>
              <SectionCard title="Losers" bodyClassName="p-0">
                <DataTable
                  columns={stockCols}
                  rows={(view ?? data).losers}
                  rowKey={(s) => s.symbol}
                  searchable
                  searchPlaceholder="Filter losers…"
                />
              </SectionCard>
            </div>
          )}

          {tab === "Sectors" && (
            <SectionCard title="Sector Performance">
              <div className="flex flex-col gap-1.5">
                {data.sectors.map((s) => (
                  <SectorBar key={s.sector} s={s} />
                ))}
              </div>
            </SectionCard>
          )}

          {tab === "Heat-map" && (
            <SectionCard title="Change Heat-map" bodyClassName="p-3">
              <Heatmap rows={(view ?? data).heatmap} />
            </SectionCard>
          )}

          {tab === "Signals" && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SignalCard label="Gap Up" tone="pos" syms={data.signals.gap_up} />
              <SignalCard label="Gap Down" tone="neg" syms={data.signals.gap_down} />
              <SignalCard label="Near Day High" tone="pos" syms={data.signals.near_day_high} />
              <SignalCard label="Near Day Low" tone="neg" syms={data.signals.near_day_low} />
            </div>
          )}

          {tab === "Most Active" && (
            <SectionCard title="Most Active (by traded value)" bodyClassName="p-0">
              <DataTable
                columns={[
                  ...stockCols.slice(0, 3),
                  {
                    key: "val",
                    header: "Value",
                    align: "right",
                    cell: (s) => inrCompact(s.value),
                    sortValue: (s) => s.value,
                  },
                ]}
                rows={(view ?? data).most_active}
                rowKey={(s) => s.symbol}
                searchable
                searchPlaceholder="Filter…"
                initialSort={{ key: "val", dir: "desc" }}
              />
            </SectionCard>
          )}

          <p className="text-xs text-fg-faint">
            {data.constituent_count} constituents · as of {new Date(data.as_of).toLocaleString()} ·
            auto-refreshes every 30s. Live Zerodha quotes — nothing simulated.
          </p>
        </>
      )}
    </div>
  );
}

function LiveClock({
  updatedAt,
  fetching,
  onRefresh,
}: {
  updatedAt: number;
  fetching: boolean;
  onRefresh: () => void;
}) {
  const now = useNow(1000);
  const secs = updatedAt ? Math.max(0, Math.round((now - updatedAt) / 1000)) : null;
  return (
    <button
      type="button"
      onClick={onRefresh}
      className="flex h-8 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
      title="Refresh now"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", fetching ? "bg-accent" : "bg-pos")} />
      <RefreshCw className={cn("h-3.5 w-3.5", fetching && "animate-spin")} />
      {secs == null ? "Refresh" : secs <= 2 ? "live" : `${secs}s ago`}
    </button>
  );
}

function BreadthStrip({
  b,
}: {
  b: { advances: number; declines: number; unchanged: number; total: number; ad_ratio: number | null };
}) {
  const t = Math.max(b.total, 1);
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-xs">
      <span className="shrink-0 font-medium text-fg-muted">Breadth</span>
      <span className="text-pos tabular-nums">{b.advances}▲</span>
      <span className="text-fg-faint tabular-nums">{b.unchanged}=</span>
      <span className="text-neg tabular-nums">{b.declines}▼</span>
      <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-elevated">
        <div className="bg-pos" style={{ width: `${(b.advances / t) * 100}%` }} />
        <div className="bg-line-strong" style={{ width: `${(b.unchanged / t) * 100}%` }} />
        <div className="bg-neg" style={{ width: `${(b.declines / t) * 100}%` }} />
      </div>
      <span className="shrink-0 text-fg-muted">
        A/D <span className="font-medium text-fg tabular-nums">{b.ad_ratio ?? "–"}</span>
      </span>
    </div>
  );
}

function SignalCard({ label, tone, syms }: { label: string; tone: "pos" | "neg"; syms: string[] }) {
  const openStock = useSym();
  return (
    <SectionCard title={`${label} (${syms.length})`}>
      <div className="flex flex-wrap gap-1">
        {syms.length === 0 && <span className="text-xs text-fg-faint">—</span>}
        {syms.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => openStock(s)}
            className={cn("rounded px-1.5 py-0.5 text-[11px] hover:underline", tone === "pos" ? "bg-pos/10 text-pos" : "bg-neg/10 text-neg")}
          >
            {s}
          </button>
        ))}
      </div>
    </SectionCard>
  );
}

function SectorBar({ s }: { s: SectorRow }) {
  const w = Math.min(Math.abs(s.avg_change_pct) / 3, 1) * 50;
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-36 shrink-0 truncate text-fg-muted">{s.sector}</span>
      <div className="relative flex h-4 flex-1 items-center">
        <span className="absolute left-1/2 h-full w-px bg-line" />
        <span
          className={cn("absolute h-2.5 rounded", s.avg_change_pct >= 0 ? "bg-pos" : "bg-neg")}
          style={s.avg_change_pct >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
        />
      </div>
      <span className={cn("w-14 shrink-0 text-right tabular-nums", pctClass(s.avg_change_pct))}>{sign(s.avg_change_pct)}</span>
      <span className="w-16 shrink-0 text-right text-[11px] text-fg-faint">{s.advances}▲ {s.declines}▼</span>
    </div>
  );
}

function Heatmap({ rows }: { rows: { symbol: string; sector: string; change_pct: number }[] }) {
  const openStock = useSym();
  const bySector = useMemo(() => {
    const m = new Map<string, typeof rows>();
    for (const r of rows) {
      const arr = m.get(r.sector) ?? [];
      arr.push(r);
      m.set(r.sector, arr);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);
  return (
    <div className="flex flex-col gap-3">
      {bySector.map(([sector, items]) => (
        <div key={sector}>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">{sector}</p>
          <div className="grid grid-cols-3 gap-1 sm:grid-cols-5 md:grid-cols-8">
            {items.map((it) => (
              <button
                key={it.symbol}
                type="button"
                onClick={() => openStock(it.symbol)}
                style={heatStyle(it.change_pct)}
                className="rounded p-1.5 text-center hover:ring-1 hover:ring-accent"
                title={`${it.symbol} ${sign(it.change_pct)}`}
              >
                <p className="truncate text-[11px] font-medium text-fg">{it.symbol}</p>
                <p className="text-[11px] tabular-nums text-fg">{sign(it.change_pct, 1)}</p>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
