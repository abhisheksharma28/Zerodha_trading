import { useMemo, useState } from "react";

import {
  DEEP_DIVE_SECTIONS,
  type FactorRow,
  type ScreenerDeepDive,
  type ScreenerRating,
  type Verdict,
} from "@/api/screener";
import { DataTable, type Column } from "@/components/DataTable";
import { SectionCard } from "@/components/SectionCard";
import { useScreenerDeepDive, useScreenerRating, useScreenerRatings } from "@/hooks/useScreener";
import { num } from "@/lib/format";
import { useStockDrawer } from "@/lib/stockDrawer";
import { cn } from "@/lib/utils";

const TABS: { key: Verdict; label: string }[] = [
  { key: "BUY", label: "Buy" },
  { key: "HOLD", label: "Hold" },
  { key: "AVOID", label: "Avoid" },
];

const verdictCls: Record<Verdict, string> = {
  BUY: "text-pos",
  HOLD: "text-fg-muted",
  AVOID: "text-neg",
};
const confCls: Record<string, string> = {
  HIGH: "bg-pos/10 text-pos",
  MEDIUM: "bg-amber-400/15 text-amber-600",
  LOW: "bg-neg/10 text-neg",
};

const pct = (v: number | null | undefined, d = 1) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`;
const scoreCls = (s: number | null) =>
  s == null ? "text-fg-faint" : s >= 66 ? "text-pos" : s < 40 ? "text-neg" : "text-fg-muted";

function ScoreBar({ v }: { v: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-elevated">
        <div
          className={cn("h-full", v >= 66 ? "bg-pos" : v < 40 ? "bg-neg" : "bg-line-strong")}
          style={{ width: `${Math.max(2, Math.min(100, v))}%` }}
        />
      </div>
      <span className="tabular-nums">{v.toFixed(0)}</span>
    </div>
  );
}

export function ScreenerPanel() {
  const { data, isLoading } = useScreenerRatings();
  const [tab, setTab] = useState<Verdict>("BUY");
  const [sector, setSector] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const { open: openStock } = useStockDrawer();

  const rows = useMemo(() => {
    const all = data?.available ? data.ratings : [];
    return all.filter((r) => r.verdict === tab && (!sector || r.sector === sector));
  }, [data, tab, sector]);

  const cols: Column<ScreenerRating>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Stock",
        cell: (r) => (
          <div>
            <span className="font-medium text-fg">{r.symbol}</span>
            {r.name && r.name !== r.symbol && (
              <span className="ml-1 hidden text-[11px] text-fg-faint md:inline">{r.name}</span>
            )}
          </div>
        ),
        sortValue: (r) => r.symbol,
      },
      { key: "sector", header: "Sector", cell: (r) => r.sector ?? "–", sortValue: (r) => r.sector ?? "" },
      {
        key: "ltp",
        header: "LTP",
        align: "right",
        cell: (r) => (r.ltp == null ? "–" : num(r.ltp)),
        sortValue: (r) => r.ltp,
      },
      {
        key: "h52",
        header: "vs 52w H",
        align: "right",
        cell: (r) => <span className={r.pct_from_52w_high != null && r.pct_from_52w_high < -25 ? "text-neg" : "text-fg-muted"}>{pct(r.pct_from_52w_high)}</span>,
        sortValue: (r) => r.pct_from_52w_high,
      },
      {
        key: "composite",
        header: "Score",
        align: "right",
        cell: (r) => <div className="flex justify-end"><ScoreBar v={r.composite} /></div>,
        sortValue: (r) => r.composite,
      },
      { key: "value", header: "Val", align: "right", cell: (r) => <span className={scoreCls(r.scores.value)}>{r.scores.value?.toFixed(0) ?? "–"}</span>, sortValue: (r) => r.scores.value },
      { key: "quality", header: "Qual", align: "right", cell: (r) => <span className={scoreCls(r.scores.quality)}>{r.scores.quality?.toFixed(0) ?? "–"}</span>, sortValue: (r) => r.scores.quality },
      { key: "growth", header: "Grw", align: "right", cell: (r) => <span className={scoreCls(r.scores.growth)}>{r.scores.growth?.toFixed(0) ?? "–"}</span>, sortValue: (r) => r.scores.growth },
      { key: "technical", header: "Tech", align: "right", cell: (r) => <span className={scoreCls(r.scores.technical)}>{r.scores.technical?.toFixed(0) ?? "–"}</span>, sortValue: (r) => r.scores.technical },
      {
        key: "confidence",
        header: "Conf",
        align: "right",
        cell: (r) => (
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", confCls[r.confidence])}>
            {r.confidence[0]}
          </span>
        ),
        sortValue: (r) => ({ HIGH: 3, MEDIUM: 2, LOW: 1 })[r.confidence],
      },
    ],
    [],
  );

  if (isLoading) return <p className="py-10 text-center text-sm text-fg-faint">Loading the screen…</p>;

  if (!data?.available) {
    return (
      <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-600 dark:text-amber-400">
        {data?.reason ?? "The screener hasn't run yet."}{" "}
        {data?.last_run?.error && <span className="block text-xs opacity-80">Last error: {data.last_run.error}</span>}
      </div>
    );
  }

  const s = data.summary;

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-line bg-surface p-3 text-xs text-fg-muted">
        <p>
          <span className="font-medium text-fg">{s.total}</span> liquid NSE names scored on a transparent
          composite of <span className="text-fg">value · quality · growth · technical</span> (0–100 each,
          ranked within sector). <span className="text-pos">{s.buy} Buy</span> ·{" "}
          <span>{s.hold} Hold</span> · <span className="text-neg">{s.avoid} Avoid</span>.
        </p>
        <p className="mt-1 text-[11px] text-fg-faint">
          Not advice — a screen with its working shown. A name with thin data is capped at Hold and marked
          low-confidence. As of {data.as_of ? new Date(data.as_of).toLocaleString() : "—"}
          {data.last_run?.finished_at && ` · swept ${new Date(data.last_run.finished_at).toLocaleString()}`}.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-md border border-line-strong bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium",
                tab === t.key ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
              )}
            >
              {t.label}{" "}
              <span className="tabular-nums opacity-70">
                {t.key === "BUY" ? s.buy : t.key === "HOLD" ? s.hold : s.avoid}
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
          {(data.sectors ?? []).map((sec) => (
            <option key={sec} value={sec}>
              {sec}
            </option>
          ))}
        </select>
      </div>

      {selected && <ScoreBreakdown symbol={selected} onClose={() => setSelected(null)} onOpenStock={() => openStock("NSE", selected)} />}

      <SectionCard title={`${TABS.find((t) => t.key === tab)?.label} — ${rows.length}`} bodyClassName="p-0">
        <DataTable
          columns={cols}
          rows={rows}
          rowKey={(r) => r.symbol}
          onRowClick={(r) => setSelected(r.symbol)}
          searchable
          searchPlaceholder="Filter by symbol / name / sector…"
          initialSort={{ key: "composite", dir: tab === "AVOID" ? "asc" : "desc" }}
        />
      </SectionCard>
    </div>
  );
}

function FactorList({ title, rows }: { title: string; rows: FactorRow[] }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">{title}</p>
      <div className="flex flex-col gap-0.5">
        {rows.map((f) => (
          <div key={f.metric} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="text-fg-muted">{f.metric}</span>
            <span className="tabular-nums text-fg-faint">
              {f.raw == null ? "n/a" : num(f.raw, 2)}
              {f.score != null && <span className={cn("ml-2", scoreCls(f.score))}>{f.score.toFixed(0)}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScoreBreakdown({
  symbol,
  onClose,
  onOpenStock,
}: {
  symbol: string;
  onClose: () => void;
  onOpenStock: () => void;
}) {
  const { data, isLoading } = useScreenerRating(symbol);
  const dive = useScreenerDeepDive();
  const [showDive, setShowDive] = useState(false);

  const runDive = (refresh = false) => {
    setShowDive(true);
    dive.mutate({ symbol, refresh });
  };

  return (
    <SectionCard
      title={`${symbol} — score breakdown`}
      bodyClassName="p-3"
    >
      <div className="mb-2 flex items-center justify-end gap-3 text-[11px]">
        <button
          type="button"
          onClick={() => runDive(false)}
          disabled={dive.isPending}
          className="font-medium text-accent hover:underline disabled:opacity-50"
        >
          {dive.isPending ? "Generating deep-dive…" : "Deep dive"}
        </button>
        <button type="button" onClick={onOpenStock} className="text-accent hover:underline">
          Open full stock view
        </button>
        <button type="button" onClick={onClose} className="text-fg-faint hover:text-fg">
          close
        </button>
      </div>
      {isLoading || !data?.available ? (
        <p className="py-4 text-center text-xs text-fg-faint">
          {data && !data.available ? data.reason : "Loading…"}
        </p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className={cn("font-semibold", verdictCls[data.verdict])}>{data.verdict}</span>
            <span className="text-fg-muted">
              composite <span className="font-semibold text-fg tabular-nums">{data.composite.toFixed(0)}</span>
            </span>
            <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", confCls[data.confidence])}>
              {data.confidence} confidence
            </span>
            <span className="text-fg-faint">
              ranked vs {data.factors.peer_count} {data.factors.peer_basis} peers · data{" "}
              {(data.data_completeness * 100).toFixed(0)}% complete
            </span>
          </div>
          {data.notes && <p className="mb-2 text-[11px] text-amber-600">{data.notes}</p>}
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
            <FactorList title={`Value ${data.scores.value?.toFixed(0) ?? "–"}`} rows={data.factors.value} />
            <FactorList title={`Quality ${data.scores.quality?.toFixed(0) ?? "–"}`} rows={data.factors.quality} />
            <FactorList title={`Growth ${data.scores.growth?.toFixed(0) ?? "–"}`} rows={data.factors.growth} />
            <FactorList title={`Technical ${data.scores.technical?.toFixed(0) ?? "–"}`} rows={data.factors.technical} />
          </div>
        </>
      )}

      {showDive && (
        <div className="mt-4 border-t border-line pt-3">
          {dive.isPending && (
            <p className="py-4 text-center text-xs text-fg-faint">
              Writing the deep-dive from {symbol}'s numbers — this takes ~15–30s…
            </p>
          )}
          {dive.isError && (
            <p className="py-2 text-xs text-neg">Deep-dive request failed. Try again.</p>
          )}
          {dive.data && <DeepDiveBody dd={dive.data} onRegenerate={() => runDive(true)} regenerating={dive.isPending} />}
        </div>
      )}
    </SectionCard>
  );
}

function DeepDiveBody({
  dd,
  onRegenerate,
  regenerating,
}: {
  dd: ScreenerDeepDive;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  if (!dd.available) {
    return (
      <div className="rounded-md border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-600 dark:text-amber-400">
        <p className="font-medium">Deep-dive unavailable.</p>
        <p className="mt-0.5">{dd.reason}</p>
        {dd.hint && <p className="mt-1 opacity-80">{dd.hint}</p>}
        {dd.raw && (
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-bg/50 p-2 text-[11px] text-fg-muted">
            {dd.raw}
          </pre>
        )}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-fg-faint">
        <span>
          Generated by {dd.model}
          {dd.generated_at && ` · ${new Date(dd.generated_at).toLocaleString()}`}
          {dd.stale && " · stale"}
        </span>
        <button
          type="button"
          onClick={onRegenerate}
          disabled={regenerating}
          className="text-accent hover:underline disabled:opacity-50"
        >
          regenerate
        </button>
      </div>
      <p className="rounded-md bg-elevated/50 px-2.5 py-1.5 text-[11px] text-fg-faint">
        Written strictly from the screener's own numbers + a free fundamentals feed. Sections it can't
        support say "Not enough data." Not investment advice.
      </p>
      {DEEP_DIVE_SECTIONS.map(([key, label]) => {
        const body = dd.sections?.[key]?.trim();
        if (!body) return null;
        const empty = /^not enough data\.?$/i.test(body);
        return (
          <div key={key}>
            <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{label}</p>
            <p
              className={cn(
                "mt-0.5 whitespace-pre-wrap text-[13px] leading-relaxed",
                empty ? "italic text-fg-faint" : "text-fg",
              )}
            >
              {body}
            </p>
          </div>
        );
      })}
    </div>
  );
}
