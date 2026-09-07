import { useMemo, useState } from "react";

import type { TaGauge, TechnicalRatingRow, TechnicalVerdict } from "@/api/screener";
import { DataTable, type Column } from "@/components/DataTable";
import { ScreenerScopeControl } from "@/components/insights/ScreenerScopeControl";
import { SectionCard } from "@/components/SectionCard";
import { useTechnicalRatings } from "@/hooks/useScreener";
import { num } from "@/lib/format";
import { useStockDrawer } from "@/lib/stockDrawer";
import { cn } from "@/lib/utils";

const TABS: { key: TechnicalVerdict; label: string }[] = [
  { key: "STRONG_BUY", label: "Strong Buy" },
  { key: "BUY", label: "Buy" },
  { key: "NEUTRAL", label: "Neutral" },
  { key: "SELL", label: "Sell" },
  { key: "STRONG_SELL", label: "Strong Sell" },
];

const label = (v: TechnicalVerdict) => v.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const toneOf = (v: TechnicalVerdict): "pos" | "neg" | "muted" =>
  v === "STRONG_BUY" || v === "BUY" ? "pos" : v === "STRONG_SELL" || v === "SELL" ? "neg" : "muted";
const toneCls = { pos: "text-pos", neg: "text-neg", muted: "text-fg-muted" };
const pct = (v: number | null | undefined) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);

function Donut({ g }: { g: TaGauge }) {
  const total = Math.max(1, g.buy + g.neutral + g.sell);
  const r = 30;
  const c = 2 * Math.PI * r;
  const tone = toneOf(g.verdict);
  const color =
    tone === "pos" ? "var(--color-pos)" : tone === "neg" ? "var(--color-neg)" : "var(--color-accent)";
  const filled = ((g.buy + g.sell) / total) * c;
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative h-16 w-16">
        <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90">
          <circle cx="36" cy="36" r={r} fill="none" stroke="var(--color-line-strong)" strokeWidth="6" />
          <circle
            cx="36"
            cy="36"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${filled} ${c - filled}`}
          />
        </svg>
        <span className={cn("absolute inset-0 flex items-center justify-center text-[10px] font-semibold", toneCls[tone])}>
          {label(g.verdict).replace("Strong ", "")}
        </span>
      </div>
      <p className="text-center text-[10px] leading-tight text-fg-faint">{g.label}</p>
      <p className="text-[10px] text-fg-faint">
        <span className="text-pos">{g.buy}</span> · {g.neutral} · <span className="text-neg">{g.sell}</span>
      </p>
    </div>
  );
}

const SIGNAL_LABELS: Record<string, string> = {
  price_vs_sma20: "Price vs SMA 20",
  price_vs_ema20: "Price vs EMA 20",
  price_vs_ema50: "Price vs EMA 50",
  price_vs_ema200: "Price vs EMA 200",
  rsi14: "RSI (14)",
  macd_hist: "MACD histogram",
  price_vs_vwap20: "Price vs 20-bar VWAP",
  roc10: "10-day rate of change",
  bollinger20: "Bollinger (20, 2)",
};
const sigCls = (v: number) => (v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-fg-faint");
const sigWord = (v: number) => (v > 0 ? "Buy" : v < 0 ? "Sell" : "Neutral");

function Breakdown({ row, onClose, onOpenStock }: { row: TechnicalRatingRow; onClose: () => void; onOpenStock: () => void }) {
  const d = row.ta_detail;
  return (
    <SectionCard title={`${row.symbol} — technical rating`} bodyClassName="p-3">
      <div className="mb-3 flex items-center justify-between gap-2 text-[11px]">
        <span className="text-fg-faint">
          net signal {d.score >= 0 ? "+" : ""}
          {d.score.toFixed(2)} · RSI {d.readings.rsi14 ?? "–"} · ROC {d.readings.roc10_pct ?? "–"}%
        </span>
        <span className="flex gap-3">
          <button type="button" onClick={onOpenStock} className="text-accent hover:underline">
            Open full stock view
          </button>
          <button type="button" onClick={onClose} className="text-fg-faint hover:text-fg">
            close
          </button>
        </span>
      </div>
      <div className="flex justify-around gap-2 border-b border-line pb-3">
        <Donut g={d.gauges.moving_average} />
        <Donut g={d.gauges.overall} />
        <Donut g={d.gauges.technical_indicators} />
      </div>
      <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-3">
        {Object.entries(d.signals).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between text-[11px]">
            <span className="text-fg-muted">{SIGNAL_LABELS[k] ?? k}</span>
            <span className={sigCls(v)}>{sigWord(v)}</span>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

export function TechnicalRatingsPanel() {
  const { data, isLoading } = useTechnicalRatings();
  const [tab, setTab] = useState<TechnicalVerdict>("STRONG_BUY");
  const [sector, setSector] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const { open: openStock } = useStockDrawer();

  const rows = useMemo(
    () =>
      (data?.available ? data.ratings : []).filter(
        (r) => r.ta_verdict === tab && (!sector || r.sector === sector),
      ),
    [data, tab, sector],
  );
  const selectedRow = useMemo(
    () => (data?.available ? data.ratings.find((r) => r.symbol === selected) : undefined),
    [data, selected],
  );

  const cols: Column<TechnicalRatingRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Stock",
        cell: (r) => (
          <span>
            <span className="font-medium text-fg">{r.symbol}</span>
            {r.name && r.name !== r.symbol && (
              <span className="ml-1 hidden text-[11px] text-fg-faint md:inline">{r.name}</span>
            )}
          </span>
        ),
        sortValue: (r) => r.symbol,
      },
      { key: "sector", header: "Sector", cell: (r) => r.sector ?? "–", sortValue: (r) => r.sector ?? "" },
      { key: "ltp", header: "LTP", align: "right", cell: (r) => (r.ltp == null ? "–" : num(r.ltp)), sortValue: (r) => r.ltp },
      {
        key: "h52",
        header: "vs 52w H",
        align: "right",
        cell: (r) => <span className="text-fg-muted">{pct(r.pct_from_52w_high)}</span>,
        sortValue: (r) => r.pct_from_52w_high,
      },
      {
        key: "ma",
        header: "Moving avg",
        align: "right",
        cell: (r) => {
          const g = r.ta_detail.gauges.moving_average;
          return (
            <span className="tabular-nums text-[11px]">
              <span className="text-pos">{g.buy}</span>/<span className="text-neg">{g.sell}</span>
            </span>
          );
        },
        sortValue: (r) => r.ta_detail.gauges.moving_average.buy - r.ta_detail.gauges.moving_average.sell,
      },
      {
        key: "ti",
        header: "Indicators",
        align: "right",
        cell: (r) => {
          const g = r.ta_detail.gauges.technical_indicators;
          return (
            <span className="tabular-nums text-[11px]">
              <span className="text-pos">{g.buy}</span>/<span className="text-neg">{g.sell}</span>
            </span>
          );
        },
        sortValue: (r) =>
          r.ta_detail.gauges.technical_indicators.buy - r.ta_detail.gauges.technical_indicators.sell,
      },
      {
        key: "score",
        header: "Net",
        align: "right",
        cell: (r) => (
          <span className={cn("tabular-nums font-medium", toneCls[toneOf(r.ta_verdict ?? "NEUTRAL")])}>
            {(r.ta_score ?? 0) >= 0 ? "+" : ""}
            {(r.ta_score ?? 0).toFixed(2)}
          </span>
        ),
        sortValue: (r) => r.ta_score,
      },
    ],
    [],
  );

  if (isLoading) return <p className="py-10 text-center text-sm text-fg-faint">Loading technical ratings…</p>;
  if (!data?.available) {
    return (
      <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-600 dark:text-amber-400">
        {data?.reason ?? "No technical ratings yet — the screener sweep hasn't run."}
      </div>
    );
  }
  const su = data.summary;

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-line bg-surface p-3 text-xs text-fg-muted">
        <p>
          The same 9-signal gauge as a stock's <span className="text-fg">Investment recommendations</span> widget —
          4 moving-average checks (price vs SMA20 / EMA20 / EMA50 / EMA200) + 5 indicators (RSI, MACD, VWAP, ROC,
          Bollinger) — run over every screened name's daily candles.
        </p>
        <p className="mt-1 text-[11px] text-fg-faint">
          Purely technical, EOD. As of {data.as_of ? new Date(data.as_of).toLocaleString() : "—"}. Not advice.
        </p>
      </div>

      <ScreenerScopeControl scope={data.scope} scopes={data.scopes} sweeping={data.sweeping} />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-md border border-line-strong bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium",
                tab === t.key ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
              )}
            >
              {t.label}{" "}
              <span className="tabular-nums opacity-70">
                {su[t.key.toLowerCase() as keyof typeof su] as number}
              </span>
            </button>
          ))}
        </div>
        <select
          value={sector}
          onChange={(e) => setSector(e.target.value)}
          className="h-8 rounded-md border border-line bg-surface px-2 text-xs"
        >
          <option value="">All sectors</option>
          {(data.sectors ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {selectedRow && (
        <Breakdown
          row={selectedRow}
          onClose={() => setSelected(null)}
          onOpenStock={() => openStock("NSE", selectedRow.symbol)}
        />
      )}

      <SectionCard title={`${TABS.find((t) => t.key === tab)?.label} — ${rows.length}`} bodyClassName="p-0">
        <DataTable
          columns={cols}
          rows={rows}
          rowKey={(r) => r.symbol}
          onRowClick={(r) => setSelected(r.symbol)}
          searchable
          searchPlaceholder="Filter by symbol / name / sector…"
          initialSort={{ key: "score", dir: tab === "SELL" || tab === "STRONG_SELL" ? "asc" : "desc" }}
        />
      </SectionCard>
    </div>
  );
}
