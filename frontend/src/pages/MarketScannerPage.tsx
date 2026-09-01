import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RefreshCw } from "lucide-react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Card, CardContent } from "@/components/ui/card";
import { useMarketOverview } from "@/hooks/useMarket";
import type { MarketQuoteRow, SectorRow } from "@/types/api";
import { cn } from "@/lib/utils";

const TABS = ["Movers", "Sectors", "Heat-map", "Signals", "Most Active"] as const;

const pctClass = (p?: number | null) =>
  p == null ? "text-fg-muted" : p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-fg-muted";
const sign = (p?: number | null, d = 2) => (p == null ? "–" : `${p >= 0 ? "+" : ""}${p.toFixed(d)}%`);
const fmtVol = (v?: number | null) =>
  v == null ? "–" : v >= 1e7 ? `${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : `${v}`;
const heatStyle = (p: number): React.CSSProperties => {
  const t = Math.max(-3, Math.min(3, p)) / 3;
  const a = 0.12 + 0.5 * Math.abs(t);
  return { backgroundColor: t >= 0 ? `rgba(52,211,153,${a})` : `rgba(248,113,113,${a})` };
};

function SymLink({ sym }: { sym: string }) {
  return (
    <Link
      to={`/charting?symbol=NSE:${encodeURIComponent(sym)}`}
      className="font-medium text-fg hover:text-accent hover:underline"
    >
      {sym}
    </Link>
  );
}

export default function MarketScannerPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Movers");
  const { data, isFetching, refetch, dataUpdatedAt } = useMarketOverview("nifty50");

  const stockCols: Column<MarketQuoteRow>[] = useMemo(
    () => [
      { key: "sym", header: "Symbol", cell: (s) => <SymLink sym={s.symbol} /> },
      {
        key: "ltp",
        header: "LTP",
        align: "right",
        cell: (s) => (s.ltp == null ? "–" : s.ltp.toLocaleString("en-IN")),
      },
      { key: "chg", header: "Chg %", align: "right", cell: (s) => <span className={pctClass(s.change_pct)}>{sign(s.change_pct)}</span> },
      { key: "vol", header: "Volume", align: "right", cell: (s) => fmtVol(s.volume) },
    ],
    [],
  );

  if (data && !data.available) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Market Scanner" subtitle="Live NSE market breadth, movers and sectors." />
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
        title="Market Scanner"
        subtitle="Live NSE breadth, movers, sectors and heat-map — real Zerodha quotes."
        actions={
          <button
            type="button"
            onClick={() => refetch()}
            className="flex h-8 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "Refresh"}
          </button>
        }
      />

      {!data ? (
        <p className="text-sm text-fg-faint">Loading market data…</p>
      ) : (
        <>
          {/* index strip */}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {data.indices.map((ix) => (
              <button
                key={ix.symbol}
                type="button"
                onClick={() => navigate(`/charting?symbol=NSE:${encodeURIComponent(ix.symbol)}`)}
                className="min-w-[9rem] shrink-0 rounded-lg border border-line bg-surface px-3 py-2 text-left hover:border-line-strong"
              >
                <p className="truncate text-[11px] text-fg-faint">{ix.name}</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums">{ix.ltp?.toLocaleString("en-IN")}</p>
                <p className={cn("text-xs tabular-nums", pctClass(ix.change_pct))}>{sign(ix.change_pct)}</p>
              </button>
            ))}
          </div>

          {/* above-the-fold: breadth + top 5 gainers + top 5 losers */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <SectionCard title="Market Breadth">
              <Breadth b={data.breadth} />
            </SectionCard>
            <SectionCard title="Top Gainers" bodyClassName="p-0">
              <DataTable columns={stockCols} rows={data.gainers.slice(0, 6)} rowKey={(s) => s.symbol} />
            </SectionCard>
            <SectionCard title="Top Losers" bodyClassName="p-0">
              <DataTable columns={stockCols} rows={data.losers.slice(0, 6)} rowKey={(s) => s.symbol} />
            </SectionCard>
          </div>

          {/* tabs for the rest */}
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
              <SectionCard title="All Gainers" bodyClassName="p-0">
                <DataTable columns={stockCols} rows={data.gainers} rowKey={(s) => s.symbol} />
              </SectionCard>
              <SectionCard title="All Losers" bodyClassName="p-0">
                <DataTable columns={stockCols} rows={data.losers} rowKey={(s) => s.symbol} />
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
              <Heatmap rows={data.heatmap} />
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
                    cell: (s) => (s.value == null ? "–" : `₹${(s.value / 1e7).toFixed(1)} Cr`),
                  },
                ]}
                rows={data.most_active}
                rowKey={(s) => s.symbol}
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

function Breadth({ b }: { b: { advances: number; declines: number; unchanged: number; total: number; ad_ratio: number | null } }) {
  const t = Math.max(b.total, 1);
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-elevated">
        <div className="bg-pos" style={{ width: `${(b.advances / t) * 100}%` }} />
        <div className="bg-line-strong" style={{ width: `${(b.unchanged / t) * 100}%` }} />
        <div className="bg-neg" style={{ width: `${(b.declines / t) * 100}%` }} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-sm">
        <div><p className="text-lg font-semibold text-pos tabular-nums">{b.advances}</p><p className="text-[11px] text-fg-faint">Advancing</p></div>
        <div><p className="text-lg font-semibold text-fg-muted tabular-nums">{b.unchanged}</p><p className="text-[11px] text-fg-faint">Unchanged</p></div>
        <div><p className="text-lg font-semibold text-neg tabular-nums">{b.declines}</p><p className="text-[11px] text-fg-faint">Declining</p></div>
      </div>
      <p className="mt-2 text-center text-xs text-fg-muted">A/D ratio <span className="font-medium text-fg">{b.ad_ratio ?? "–"}</span></p>
    </div>
  );
}

function SignalCard({ label, tone, syms }: { label: string; tone: "pos" | "neg"; syms: string[] }) {
  return (
    <SectionCard title={`${label} (${syms.length})`}>
      <div className="flex flex-wrap gap-1">
        {syms.length === 0 && <span className="text-xs text-fg-faint">—</span>}
        {syms.map((s) => (
          <Link
            key={s}
            to={`/charting?symbol=NSE:${encodeURIComponent(s)}`}
            className={cn("rounded px-1.5 py-0.5 text-[11px] hover:underline", tone === "pos" ? "bg-pos/10 text-pos" : "bg-neg/10 text-neg")}
          >
            {s}
          </Link>
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
              <Link
                key={it.symbol}
                to={`/charting?symbol=NSE:${encodeURIComponent(it.symbol)}`}
                style={heatStyle(it.change_pct)}
                className="rounded p-1.5 text-center hover:ring-1 hover:ring-accent"
                title={`${it.symbol} ${sign(it.change_pct)}`}
              >
                <p className="truncate text-[11px] font-medium text-fg">{it.symbol}</p>
                <p className="text-[11px] tabular-nums text-fg">{sign(it.change_pct, 1)}</p>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
