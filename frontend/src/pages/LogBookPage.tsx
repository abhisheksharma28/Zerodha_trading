import { useState } from "react";
import { Link } from "react-router-dom";

import type { LogbookFilters, ScanRecommendation } from "@/api/marketScanner";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useScannerLogbook } from "@/hooks/useMarketScanner";
import { num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const OUTCOMES = ["", "TARGET", "SL", "NEUTRAL", "INVALIDATED"];
const HORIZONS = ["", "INTRADAY", "SWING"];
const DIRECTIONS = ["", "LONG", "SHORT"];
const outcomeTone: Record<string, "success" | "destructive" | "warning" | "default"> = {
  TARGET: "success",
  SL: "destructive",
  NEUTRAL: "warning",
  INVALIDATED: "default",
};

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-fg-faint">{label}</p>
      <p className={cn("mt-0.5 text-lg font-semibold tabular-nums", tone)}>{value}</p>
    </div>
  );
}

export default function LogBookPage() {
  const [filters, setFilters] = useState<LogbookFilters>({ page: 1, page_size: 100 });
  const { data, isLoading } = useScannerLogbook(filters);
  const set = (k: keyof LogbookFilters, v: string) =>
    setFilters((f) => ({ ...f, [k]: v || undefined, page: 1 }));

  const s = data?.stats;
  const cols: Column<ScanRecommendation>[] = [
    {
      key: "day",
      header: "Day",
      cell: (r) => <span className="tabular-nums text-fg-muted">{r.trading_day}</span>,
      sortValue: (r) => r.trading_day,
    },
    {
      key: "exit",
      header: "Closed",
      cell: (r) => (
        <span className="tabular-nums text-fg-faint">
          {r.exit_at ? new Date(r.exit_at).toLocaleTimeString("en-IN") : "—"}
        </span>
      ),
      sortValue: (r) => r.exit_at ?? "",
    },
    {
      key: "sym",
      header: "Instrument",
      cell: (r) =>
        r.asset_class === "EQUITY" ? (
          <Link to={`/stocks/${r.exchange}/${r.tradingsymbol}`} className="font-medium text-fg hover:text-accent">
            {r.tradingsymbol}
          </Link>
        ) : (
          <span className="font-medium text-fg">{r.tradingsymbol}</span>
        ),
      sortValue: (r) => r.tradingsymbol,
    },
    {
      key: "dir",
      header: "Dir",
      cell: (r) => (
        <span className={cn("text-xs font-bold", r.direction === "LONG" ? "text-pos" : "text-neg")}>
          {r.direction}
        </span>
      ),
      sortValue: (r) => r.direction,
    },
    {
      key: "horizon",
      header: "Horizon",
      cell: (r) => <span className="text-fg-muted">{r.horizon.toLowerCase()}</span>,
      sortValue: (r) => r.horizon,
    },
    {
      key: "setup",
      header: "Setup",
      cell: (r) => <span className="text-fg-muted">{r.setup_type}</span>,
      sortValue: (r) => r.setup_type,
    },
    {
      key: "conf",
      header: "Conf",
      align: "right",
      cell: (r) => <span className="tabular-nums">{num(r.confidence, 0)}</span>,
      sortValue: (r) => r.confidence,
    },
    {
      key: "rr",
      header: "R:R",
      align: "right",
      cell: (r) => <span className="tabular-nums text-fg-muted">{num(r.rr, 2)}</span>,
      sortValue: (r) => r.rr,
    },
    {
      key: "outcome",
      header: "Outcome",
      cell: (r) => (
        <Badge variant={outcomeTone[r.outcome ?? "INVALIDATED"]} className="text-[10px]">
          {r.outcome}
        </Badge>
      ),
      sortValue: (r) => r.outcome ?? "",
    },
    {
      key: "res_pct",
      header: "Result",
      align: "right",
      cell: (r) => (
        <span
          className={cn(
            "tabular-nums font-semibold",
            (r.result_pct ?? 0) > 0 ? "text-pos" : (r.result_pct ?? 0) < 0 ? "text-neg" : "text-fg-muted",
          )}
        >
          {pctSigned(r.result_pct)}
        </span>
      ),
      sortValue: (r) => r.result_pct,
    },
    {
      key: "res_r",
      header: "R",
      align: "right",
      cell: (r) => (
        <span className="tabular-nums text-fg-faint">
          {r.result_r == null ? "—" : `${r.result_r > 0 ? "+" : ""}${num(r.result_r, 2)}`}
        </span>
      ),
      sortValue: (r) => r.result_r,
    },
    {
      key: "mae",
      header: "MAE/MFE",
      align: "right",
      cell: (r) => (
        <span className="tabular-nums text-[11px] text-fg-faint">
          {num(r.mae_pct, 1)} / {num(r.mfe_pct, 1)}
        </span>
      ),
      sortValue: (r) => r.mae_pct,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Scanner Log Book"
        subtitle="Every recommendation the Market Scanner produced, with its real outcome. Track hit-rate and expectancy over time."
      />

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-7">
        <Stat label="Resolved" value={num(s?.resolved ?? 0, 0)} />
        <Stat label="Target" value={num(s?.target ?? 0, 0)} tone="text-pos" />
        <Stat label="Stopped" value={num(s?.sl ?? 0, 0)} tone="text-neg" />
        <Stat label="Neutral" value={num(s?.neutral ?? 0, 0)} tone="text-amber-400" />
        <Stat label="Win rate" value={s?.win_rate_pct == null ? "—" : `${num(s.win_rate_pct, 1)}%`} />
        <Stat
          label="Expectancy"
          value={s?.expectancy_r == null ? "—" : `${s.expectancy_r > 0 ? "+" : ""}${num(s.expectancy_r, 2)}R`}
          tone={(s?.expectancy_r ?? 0) > 0 ? "text-pos" : (s?.expectancy_r ?? 0) < 0 ? "text-neg" : undefined}
        />
        <Stat label="Net %" value={s?.total_pct == null ? "—" : pctSigned(s.total_pct)} />
      </div>

      <SectionCard title="Filters" bodyClassName="p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">From</span>
            <Input type="date" value={filters.date_from ?? ""} onChange={(e) => set("date_from", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">To</span>
            <Input type="date" value={filters.date_to ?? ""} onChange={(e) => set("date_to", e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">Outcome</span>
            <select
              className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
              value={filters.outcome ?? ""}
              onChange={(e) => set("outcome", e.target.value)}
            >
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {o || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">Horizon</span>
            <select
              className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
              value={filters.horizon ?? ""}
              onChange={(e) => set("horizon", e.target.value)}
            >
              {HORIZONS.map((o) => (
                <option key={o} value={o}>
                  {o || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">Direction</span>
            <select
              className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
              value={filters.direction ?? ""}
              onChange={(e) => set("direction", e.target.value)}
            >
              {DIRECTIONS.map((o) => (
                <option key={o} value={o}>
                  {o || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">Setup</span>
            <select
              className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
              value={filters.setup ?? ""}
              onChange={(e) => set("setup", e.target.value)}
            >
              <option value="">any</option>
              {(data?.setups ?? []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-fg-faint">Symbol</span>
            <Input
              placeholder="e.g. RELIANCE"
              value={filters.symbol ?? ""}
              onChange={(e) => set("symbol", e.target.value)}
            />
          </label>
          <Button size="sm" variant="ghost" onClick={() => setFilters({ page: 1, page_size: 100 })}>
            Reset
          </Button>
        </div>
      </SectionCard>

      {s && Object.keys(s.by_setup).length > 0 && (
        <SectionCard title="By setup" bodyClassName="p-3">
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(s.by_setup)
              .sort((a, b) => b[1].n - a[1].n)
              .map(([name, v]) => (
                <span key={name} className="rounded-md border border-line bg-surface px-2 py-1">
                  <span className="text-fg-muted">{name}</span>{" "}
                  <span className="tabular-nums font-semibold">
                    {v.win}/{v.n}
                  </span>{" "}
                  <span className="text-fg-faint">({v.n ? num((100 * v.win) / v.n, 0) : 0}%)</span>
                </span>
              ))}
          </div>
        </SectionCard>
      )}

      <SectionCard title={`History (${data?.total ?? 0})`} bodyClassName="p-0">
        {isLoading ? (
          <p className="p-6 text-center text-sm text-fg-faint">Loading…</p>
        ) : (
          <DataTable
            columns={cols}
            rows={data?.rows ?? []}
            rowKey={(r) => r.id}
            searchable
            searchPlaceholder="Filter rows…"
            initialSort={{ key: "exit", dir: "desc" }}
            empty="No resolved recommendations yet. They appear here once a target, stop or the 15:20 close is hit."
          />
        )}
      </SectionCard>
      <p className="text-[11px] text-fg-faint">
        Outcomes are marked against the real-time price: TARGET / SL when the level trades, NEUTRAL at the
        15:20 IST square-off, INVALIDATED if a limit entry never triggered. Not a trading record — screener
        results for research.
      </p>
    </div>
  );
}
