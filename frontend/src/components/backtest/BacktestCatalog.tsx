import { useState } from "react";

import type { CatalogEntry } from "@/api/leaderboard";
import { Sparkline } from "@/components/Sparkline";
import { Button } from "@/components/ui/button";
import { useBacktestCatalog, useRefreshLeaderboard } from "@/hooks/useLeaderboard";
import { num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const VERDICT: Record<
  string,
  { label: string; cls: string }
> = {
  strong: { label: "Strong", cls: "border-pos/40 bg-pos/10 text-pos" },
  tradeable: { label: "Tradeable", cls: "border-pos/30 bg-pos/5 text-pos" },
  marginal: { label: "Marginal", cls: "border-amber-400/40 bg-amber-400/10 text-amber-500" },
  avoid: { label: "Avoid", cls: "border-neg/40 bg-neg/10 text-neg" },
  ruined: { label: "Ruined", cls: "border-neg/50 bg-neg/15 text-neg" },
  insufficient: { label: "Too few trades", cls: "border-line text-fg-muted" },
};

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span className={cn("tabular-nums text-sm font-semibold", tone)}>{value}</span>
    </div>
  );
}

function CatalogCard({ e }: { e: CatalogEntry }) {
  const [open, setOpen] = useState(false);
  const m = e.metrics ?? {};
  const v = e.summary?.verdict ?? (e.status === "not_run" ? "insufficient" : "marginal");
  const badge = VERDICT[v] ?? VERDICT.marginal;
  const ret = m.return_pct ?? null;
  const curve = e.equity_curve?.map(([, val]) => Number(val)) ?? [];

  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-fg">{e.name}</p>
          <p className="text-[11px] text-fg-faint">
            {e.category} · {e.universe} · {e.timeframe} · ~{e.years}y
            {e.stale && <span className="ml-1 text-amber-500">· config changed, re-run</span>}
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold",
            badge.cls,
          )}
        >
          {badge.label}
        </span>
      </div>

      {e.status === "not_run" ? (
        <p className="mt-3 text-xs text-fg-faint">Not run yet — hit “Refresh catalog”.</p>
      ) : (
        <>
          <div className="mt-2 grid grid-cols-4 gap-2">
            <Metric
              label="Return"
              value={ret == null ? "—" : pctSigned(ret)}
              tone={(ret ?? 0) < 0 ? "text-neg" : "text-pos"}
            />
            <Metric label="Sharpe" value={m.sharpe_ratio == null ? "—" : num(m.sharpe_ratio, 2)} />
            <Metric
              label="Max DD"
              value={m.max_drawdown_pct == null ? "—" : `${num(Math.abs(m.max_drawdown_pct), 1)}%`}
              tone="text-neg"
            />
            <Metric label="Trades" value={m.total_trades == null ? "—" : num(m.total_trades, 0)} />
          </div>
          {curve.length > 2 && (
            <div className="mt-2 h-8 w-full">
              <Sparkline data={curve} tone={(ret ?? 0) < 0 ? "neg" : "accent"} />
            </div>
          )}
          {e.summary && (
            <>
              <p className="mt-2 text-xs text-fg-muted">{e.summary.headline}</p>
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="mt-1 text-[11px] font-medium text-accent hover:underline"
              >
                {open ? "Hide the read-out" : "Read the full read-out"}
              </button>
              {open && (
                <div className="mt-2 space-y-2 text-[11px] text-fg-muted">
                  <Block title="What we did" items={e.summary.what_we_did} />
                  <Block title="What we saw" items={e.summary.what_we_saw} />
                  <Block title="What to look at" items={e.summary.what_to_look_at} />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

// the backend summary lines use **bold** — render that as <strong>, nothing else
function renderBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-fg">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function Block({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">{title}</p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
        {items.map((t, i) => (
          <li key={i}>{renderBold(t)}</li>
        ))}
      </ul>
    </div>
  );
}

export function BacktestCatalog() {
  const { data, isLoading } = useBacktestCatalog();
  const refresh = useRefreshLeaderboard();

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-fg">Strategy backtest catalog</h2>
          <p className="text-[11px] text-fg-faint">
            Every library strategy, pre-run over {data?.meta.universe ?? "NIFTY 200"} with its tuned
            preset.{" "}
            {data?.meta.last_refresh
              ? `Last run ${new Date(data.meta.last_refresh * 1000).toLocaleString("en-IN")}.`
              : "Not run yet."}{" "}
            <span className="text-fg-muted">
              {data?.meta.total_backtests ?? 0} backtests on record
              {data ? ` (${data.meta.catalog_ran} catalog · ${data.meta.user_backtests} yours)` : ""}.
            </span>
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate(undefined)}
        >
          {refresh.isPending ? "Running… (minutes)" : "Refresh catalog"}
        </Button>
      </div>

      {isLoading ? (
        <p className="py-6 text-center text-sm text-fg-faint">Loading catalog…</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data?.strategies.map((e) => <CatalogCard key={e.slug} e={e} />)}
        </div>
      )}
      <p className="text-[10px] text-fg-faint">
        Screener/backtest output over one fixed window. Not investment advice; past results do not
        predict the future. Run the robustness suite before trusting any single number.
      </p>
    </section>
  );
}
