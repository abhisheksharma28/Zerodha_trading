import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Card, CardContent } from "@/components/ui/card";
import { useMarketOverview } from "@/hooks/useMarket";
import type { MarketQuoteRow, SectorRow } from "@/types/api";
import { cn } from "@/lib/utils";

const UNIVERSES = [{ key: "nifty50", label: "NIFTY 50" }];

const pctClass = (p: number | null | undefined) =>
  p == null ? "text-fg-muted" : p > 0 ? "text-pos" : p < 0 ? "text-neg" : "text-fg-muted";

const sign = (p: number | null | undefined, d = 2) =>
  p == null ? "–" : `${p >= 0 ? "+" : ""}${p.toFixed(d)}%`;

function heatStyle(p: number): React.CSSProperties {
  const t = Math.max(-3, Math.min(3, p)) / 3;
  const a = 0.1 + 0.55 * Math.abs(t);
  return {
    backgroundColor:
      t >= 0 ? `rgba(38,194,129,${a})` : `rgba(239,77,107,${a})`,
  };
}

const fmtVol = (v: number | null | undefined) =>
  v == null ? "–" : v >= 1e7 ? `${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : v.toLocaleString("en-IN");

const fmtValue = (v: number | undefined) =>
  v == null ? "–" : `₹${(v / 1e7).toFixed(1)} Cr`;

export default function MarketScannerPage() {
  const [universe, setUniverse] = useState("nifty50");
  const { data, isFetching, refetch, dataUpdatedAt } = useMarketOverview(universe);

  const stockCols: Column<MarketQuoteRow>[] = [
    {
      key: "sym",
      header: "Symbol",
      cell: (s) => (
        <span>
          <span className="font-medium text-fg">{s.symbol}</span>
          {s.sector && <span className="ml-2 text-[11px] text-fg-faint">{s.sector}</span>}
        </span>
      ),
    },
    {
      key: "ltp",
      header: "LTP",
      align: "right",
      cell: (s) => (s.ltp == null ? "–" : s.ltp.toLocaleString("en-IN")),
    },
    {
      key: "chg",
      header: "Chg %",
      align: "right",
      cell: (s) => <span className={pctClass(s.change_pct)}>{sign(s.change_pct)}</span>,
    },
    { key: "vol", header: "Volume", align: "right", cell: (s) => fmtVol(s.volume) },
  ];

  if (data && !data.available) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Market Scanner" subtitle="Live NSE market breadth, movers and sectors." />
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
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Market Scanner"
        subtitle="Live NSE breadth, movers, sectors and a change heat-map — real quotes from your Zerodha session."
        actions={
          <div className="flex items-center gap-2">
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="h-8 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg"
            >
              {UNIVERSES.map((u) => (
                <option key={u.key} value={u.key}>
                  {u.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => refetch()}
              className="flex h-8 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
              {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "Refresh"}
            </button>
          </div>
        }
      />

      {!data ? (
        <p className="text-sm text-fg-faint">Loading market data…</p>
      ) : (
        <>
          {/* index strip */}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {data.indices.map((ix) => (
              <div
                key={ix.symbol}
                className="min-w-[9.5rem] shrink-0 rounded-lg border border-line bg-surface px-3 py-2"
              >
                <p className="truncate text-[11px] text-fg-faint">{ix.name}</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums">
                  {ix.ltp?.toLocaleString("en-IN")}
                </p>
                <p className={cn("text-xs tabular-nums", pctClass(ix.change_pct))}>
                  {ix.change != null ? `${ix.change >= 0 ? "+" : ""}${ix.change.toFixed(1)}` : "–"}{" "}
                  ({sign(ix.change_pct)})
                </p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <SectionCard title="Market Breadth">
              <BreadthBar b={data.breadth} />
            </SectionCard>
            <SectionCard title="Intraday Signals" className="lg:col-span-2">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <SignalGroup label="Gap Up" tone="pos" syms={data.signals.gap_up} />
                <SignalGroup label="Gap Down" tone="neg" syms={data.signals.gap_down} />
                <SignalGroup label="Near Day High" tone="pos" syms={data.signals.near_day_high} />
                <SignalGroup label="Near Day Low" tone="neg" syms={data.signals.near_day_low} />
              </div>
            </SectionCard>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SectionCard title="Top Gainers" bodyClassName="p-0">
              <DataTable columns={stockCols} rows={data.gainers} rowKey={(s) => s.symbol} />
            </SectionCard>
            <SectionCard title="Top Losers" bodyClassName="p-0">
              <DataTable columns={stockCols} rows={data.losers} rowKey={(s) => s.symbol} />
            </SectionCard>
          </div>

          <SectionCard title="Sector Performance">
            <div className="flex flex-col gap-1.5">
              {data.sectors.map((s) => (
                <SectorBar key={s.sector} s={s} />
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Heat-map" bodyClassName="p-3">
            <Heatmap rows={data.heatmap} />
          </SectionCard>

          <SectionCard title="Most Active (by traded value)" bodyClassName="p-0">
            <DataTable
              columns={[
                ...stockCols.slice(0, 3),
                {
                  key: "val",
                  header: "Value",
                  align: "right",
                  cell: (s) => fmtValue(s.value),
                },
              ]}
              rows={data.most_active}
              rowKey={(s) => s.symbol}
            />
          </SectionCard>

          <p className="text-xs text-fg-faint">
            {data.constituent_count} constituents · as of {new Date(data.as_of).toLocaleString()} ·
            auto-refreshes every 30s. Prices are live from Zerodha; nothing here is simulated.
          </p>
        </>
      )}
    </div>
  );
}

function BreadthBar({
  b,
}: {
  b: { advances: number; declines: number; unchanged: number; total: number; ad_ratio: number | null };
}) {
  const total = Math.max(b.total, 1);
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-elevated">
        <div className="bg-pos" style={{ width: `${(b.advances / total) * 100}%` }} />
        <div className="bg-line-strong" style={{ width: `${(b.unchanged / total) * 100}%` }} />
        <div className="bg-neg" style={{ width: `${(b.declines / total) * 100}%` }} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <p className="text-lg font-semibold text-pos tabular-nums">{b.advances}</p>
          <p className="text-[11px] text-fg-faint">Advancing</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-fg-muted tabular-nums">{b.unchanged}</p>
          <p className="text-[11px] text-fg-faint">Unchanged</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-neg tabular-nums">{b.declines}</p>
          <p className="text-[11px] text-fg-faint">Declining</p>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-fg-muted">
        A/D ratio <span className="font-medium text-fg">{b.ad_ratio ?? "–"}</span>
      </p>
    </div>
  );
}

function SignalGroup({
  label,
  tone,
  syms,
}: {
  label: string;
  tone: "pos" | "neg";
  syms: string[];
}) {
  return (
    <div>
      <p className={cn("text-xs font-medium", tone === "pos" ? "text-pos" : "text-neg")}>
        {label} <span className="text-fg-faint">({syms.length})</span>
      </p>
      <div className="mt-1 flex flex-wrap gap-1">
        {syms.length === 0 && <span className="text-xs text-fg-faint">—</span>}
        {syms.map((s) => (
          <span key={s} className="rounded bg-elevated px-1.5 py-0.5 text-[11px] text-fg-muted">
            {s}
          </span>
        ))}
      </div>
    </div>
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
          style={
            s.avg_change_pct >= 0
              ? { left: "50%", width: `${w}%` }
              : { right: "50%", width: `${w}%` }
          }
        />
      </div>
      <span className={cn("w-14 shrink-0 text-right tabular-nums", pctClass(s.avg_change_pct))}>
        {sign(s.avg_change_pct)}
      </span>
      <span className="w-16 shrink-0 text-right text-[11px] text-fg-faint">
        {s.advances}▲ {s.declines}▼
      </span>
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
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
            {sector}
          </p>
          <div className="grid grid-cols-3 gap-1 sm:grid-cols-5 md:grid-cols-8">
            {items.map((it) => (
              <div
                key={it.symbol}
                style={heatStyle(it.change_pct)}
                className="rounded p-1.5 text-center"
                title={`${it.symbol} ${sign(it.change_pct)}`}
              >
                <p className="truncate text-[11px] font-medium text-fg">{it.symbol}</p>
                <p className="text-[11px] tabular-nums text-fg">{sign(it.change_pct, 1)}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
