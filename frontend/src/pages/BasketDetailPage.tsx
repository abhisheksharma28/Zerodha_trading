import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowLeft, Loader2, Pencil, Play, Rocket, RotateCw, Trash2 } from "lucide-react";

import type { Frequency, Sleeve } from "@/api/baskets";
import { SleeveEditor } from "@/components/baskets/SleeveEditor";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useBasket,
  useBasketEvents,
  useBasketStatus,
  useDeleteBasket,
  useDeployBasket,
  useRebalanceBasket,
  useRunBasketBacktest,
  useUndeployBasket,
  useUpdateBasket,
} from "@/hooks/useBaskets";
import { inr, inrCompact, num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const AXIS = "var(--color-fg-faint)";
const GRID = "var(--color-line)";
const rupeeTick = (v: number) => inrCompact(v);

export default function BasketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data: basket, isLoading } = useBasket(id);
  const deployed = basket?.status === "deployed";
  const { data: live } = useBasketStatus(deployed ? id : undefined);
  const { data: events } = useBasketEvents(id);

  const runBacktest = useRunBasketBacktest(id ?? "");
  const deploy = useDeployBasket(id ?? "");
  const undeploy = useUndeployBasket(id ?? "");
  const rebalance = useRebalanceBasket(id ?? "");
  const del = useDeleteBasket();
  const update = useUpdateBasket(id ?? "");

  const [years, setYears] = useState(5);
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const bt = basket?.last_backtest ?? null;
  const chart = useMemo(() => {
    if (!bt) return [];
    const bench = new Map(bt.benchmark_curve.map(([d, v]) => [d, v]));
    return bt.equity_curve.map(([d, v], i) => ({
      i,
      d,
      basket: Math.round(v),
      benchmark: bench.has(d) ? Math.round(bench.get(d) as number) : null,
    }));
  }, [bt]);

  if (isLoading || !basket) {
    return <p className="py-12 text-center text-sm text-fg-faint">Loading…</p>;
  }

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      const r = (await fn()) as { skipped?: boolean; reason?: string; orders_placed?: number };
      if (r?.skipped) setMsg(r.reason ?? "Skipped.");
      else setMsg(ok + (r?.orders_placed != null ? ` — ${r.orders_placed} orders placed` : ""));
    } catch (e) {
      setMsg(
        (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data
          ?.message ??
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Action failed.",
      );
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <button
        onClick={() => nav("/baskets")}
        className="flex w-fit items-center gap-1 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All baskets
      </button>

      <PageHeader
        title={basket.name}
        subtitle={basket.description ?? undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-md border px-2 py-1 text-[11px] font-semibold capitalize",
                deployed
                  ? "border-pos/40 bg-pos/10 text-pos"
                  : "border-amber-400/40 bg-amber-400/10 text-amber-500",
              )}
            >
              {basket.status}
            </span>
            <Button size="sm" variant="outline" onClick={() => setEditing((e) => !e)}>
              <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
            </Button>
            {!deployed ? (
              <Button
                size="sm"
                disabled={deploy.isPending}
                onClick={() => act(() => deploy.mutateAsync(), "Deployed to the paper account")}
              >
                {deploy.isPending ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Rocket className="mr-1 h-3.5 w-3.5" />
                )}
                Deploy to paper
              </Button>
            ) : (
              <>
                <Button
                  size="sm"
                  disabled={rebalance.isPending}
                  onClick={() => act(() => rebalance.mutateAsync(true), "Rebalanced")}
                >
                  {rebalance.isPending ? (
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCw className="mr-1 h-3.5 w-3.5" />
                  )}
                  Rebalance now
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    act(() => undeploy.mutateAsync(true), "Undeployed and liquidated")
                  }
                >
                  Undeploy
                </Button>
              </>
            )}
            {!deployed && (
              <Button
                size="sm"
                variant="ghost"
                className="text-neg"
                onClick={() => {
                  if (confirm(`Delete "${basket.name}"?`)) {
                    del.mutate(basket.id, { onSuccess: () => nav("/baskets") });
                  }
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        }
      />

      {msg && (
        <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg-muted">
          {msg}
        </div>
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-muted">
        <span>
          Rebalance <b className="text-fg">{basket.rebalance_frequency}</b>
        </span>
        <span>
          Drift band <b className="text-fg">{basket.drift_band_pct}%</b>
        </span>
        <span>
          Capital <b className="text-fg">{inr(basket.capital)}</b>
        </span>
        <span>
          Benchmark <b className="text-fg">{basket.benchmark}</b>
        </span>
        {basket.last_rebalanced_at && (
          <span>
            Last rebalanced{" "}
            <b className="text-fg">
              {new Date(basket.last_rebalanced_at).toLocaleString("en-IN")}
            </b>
          </span>
        )}
      </div>

      {editing && (
        <EditPanel
          sleeves={basket.spec?.sleeves ?? basket.sleeves}
          frequency={basket.rebalance_frequency}
          driftBand={basket.drift_band_pct}
          capital={basket.capital}
          benchmark={basket.benchmark}
          saving={update.isPending}
          onCancel={() => setEditing(false)}
          onSave={async (payload) => {
            await update.mutateAsync(payload);
            setEditing(false);
            setMsg("Saved. Re-run the backtest to refresh the numbers.");
          }}
        />
      )}

      {deployed && live && <LivePanel live={live} />}

      <SectionCard
        title="Backtest"
        index={deployed ? 2 : 1}
        actions={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-xs text-fg-faint">
              Years
              <Input
                type="number"
                className="h-7 w-16 tabular-nums"
                value={years}
                min={1}
                max={12}
                onChange={(e) => setYears(Number(e.target.value))}
              />
            </label>
            <Button
              size="sm"
              disabled={runBacktest.isPending}
              onClick={() => act(() => runBacktest.mutateAsync(years), "Backtest complete")}
            >
              {runBacktest.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1 h-3.5 w-3.5" />
              )}
              Run backtest
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4 p-4">
          {!bt ? (
            <p className="text-sm text-fg-faint">
              Not backtested yet — hit “Run backtest”.
            </p>
          ) : (
            <>
              <p className="text-xs text-fg-faint">
                {bt.start} → {bt.end} · {bt.years}y · {bt.frequency} rebalance ·{" "}
                {bt.metrics.n_rebalances} rebalances
              </p>
              <MetricsRow m={bt.metrics} />
              <div className="h-72 w-full">
                <ResponsiveContainer>
                  <LineChart data={chart} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                    <XAxis
                      dataKey="d"
                      stroke={AXIS}
                      fontSize={11}
                      tickFormatter={(d: string) => d?.slice(0, 7)}
                      minTickGap={48}
                    />
                    <YAxis
                      stroke={AXIS}
                      fontSize={11}
                      width={70}
                      domain={["auto", "auto"]}
                      tickFormatter={rupeeTick}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--color-surface)",
                        border: "1px solid var(--color-line)",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      formatter={
                        ((v: unknown, n: unknown) => [
                          inr(Number(v)),
                          n === "basket" ? "Basket" : "Benchmark",
                        ]) as never
                      }
                    />
                    <Legend
                      formatter={(v) => (v === "basket" ? "Basket" : `Benchmark (${bt.benchmark})`)}
                    />
                    <Line
                      type="monotone"
                      dataKey="basket"
                      stroke="var(--color-accent)"
                      dot={false}
                      strokeWidth={2}
                    />
                    <Line
                      type="monotone"
                      dataKey="benchmark"
                      stroke="var(--color-fg-faint)"
                      dot={false}
                      strokeWidth={1.5}
                      strokeDasharray="4 3"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-center text-[11px] tabular-nums text-fg-muted">
                Basket ends at {inr(chart.at(-1)?.basket ?? 0)} ·{" "}
                Benchmark {inr(chart.at(-1)?.benchmark ?? 0)} · start {inr(bt.capital)}
              </p>

              {(bt.oos?.out_of_sample?.return_pct != null ||
                bt.regime_breakdown?.bull_tape) && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {bt.oos?.out_of_sample?.return_pct != null && (
                    <div className="rounded-md border border-line/70 bg-bg/40 p-2.5">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                        In-sample vs out-of-sample
                      </p>
                      <p className="mt-1 text-[11px] text-fg-muted">
                        Trained on the first ~65% of the window, tested on the rest — a
                        strong number here is not just an artefact of the early years.
                      </p>
                      <div className="mt-1.5 grid grid-cols-2 gap-2 text-xs tabular-nums">
                        <SplitCell label="In-sample" s={bt.oos.in_sample} />
                        <SplitCell label="Out-of-sample" s={bt.oos.out_of_sample} />
                      </div>
                    </div>
                  )}
                  {bt.regime_breakdown?.bull_tape && (
                    <div className="rounded-md border border-line/70 bg-bg/40 p-2.5">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                        Bull tape vs bear tape
                      </p>
                      <p className="mt-1 text-[11px] text-fg-muted">
                        Return split by whether {bt.benchmark} was above or below its own
                        200-day average that day.
                      </p>
                      <div className="mt-1.5 grid grid-cols-2 gap-2 text-xs tabular-nums">
                        <RegimeCell label="Bull tape" r={bt.regime_breakdown.bull_tape} />
                        <RegimeCell label="Bear tape" r={bt.regime_breakdown.bear_tape} />
                      </div>
                    </div>
                  )}
                </div>
              )}
              {bt.rebalances.length > 0 && <RebalanceTable rows={bt.rebalances} />}
              {bt.caveats.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-fg-faint">
                  {bt.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Sleeves" index={deployed ? 3 : 2}>
        <div className="divide-y divide-line">
          {(basket.spec?.sleeves ?? basket.sleeves).map((sl) => (
            <div key={sl.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
              <span className="w-40 font-medium text-fg">{sl.name}</span>
              <span className="tabular-nums text-fg-muted">{sl.weight_pct}%</span>
              <span className="text-xs text-fg-faint">{sl.weighting.replace("_", "-")}</span>
              <span className="text-xs text-fg-faint">
                {sl.rule.type === "none"
                  ? "hold all"
                  : `top ${sl.rule.top_k} by ${sl.rule.lookback}-bar momentum${
                      sl.rule.trend_ma ? ` > MA${sl.rule.trend_ma}` : ""
                    }`}
              </span>
              <span className="ml-auto max-w-md truncate text-xs text-fg-muted">
                {sl.members.join(", ")}
              </span>
            </div>
          ))}
        </div>
      </SectionCard>

      {events && events.length > 0 && (
        <SectionCard title="Rebalance history" index={deployed ? 4 : 3}>
          <div className="divide-y divide-line text-sm">
            {events.map((e) => (
              <div key={e.id} className="flex flex-wrap items-center gap-x-3 px-4 py-2">
                <span className="tabular-nums text-xs text-fg-faint">
                  {new Date(e.as_of).toLocaleString("en-IN")}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                    e.mode === "paper"
                      ? "bg-pos/10 text-pos"
                      : e.mode === "backtest"
                        ? "bg-accent-soft text-accent"
                        : "bg-elevated text-fg-muted",
                  )}
                >
                  {e.mode}
                </span>
                <span className="text-xs text-fg-muted">{e.orders.length} orders</span>
                <span className="text-xs text-fg-faint">{e.note}</span>
              </div>
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  );
}

function MetricsRow({ m }: { m: Record<string, number | null> }) {
  const cells: [string, string, boolean][] = [
    ["Total return", pctSigned(m.total_return_pct ?? null, 1), true],
    ["CAGR", pctSigned(m.cagr_pct ?? null, 1), true],
    ["Benchmark", pctSigned(m.benchmark_return_pct ?? null, 1), true],
    ["vs benchmark", `${(m.excess_return_pct ?? 0) >= 0 ? "+" : ""}${num(m.excess_return_pct, 1)} pts`, true],
    ["Sharpe", num(m.sharpe_ratio, 2), false],
    ["Sortino", num(m.sortino_ratio, 2), false],
    ["Calmar", num(m.calmar_ratio, 2), false],
    ["Max DD", `${num(Math.abs(m.max_drawdown_pct ?? 0), 1)}%`, false],
    ["Volatility", `${num(m.volatility_pct, 1)}%`, false],
    ["Beta", num(m.beta, 2), false],
    ["Alpha (ann.)", `${(m.alpha_pct ?? 0) >= 0 ? "+" : ""}${num(m.alpha_pct, 1)}%`, true],
    ["Info ratio", num(m.information_ratio, 2), false],
    ["Monthly win", `${num(m.monthly_win_rate_pct, 0)}%`, false],
    ["Avg hold", m.avg_holding_days == null ? "–" : `${num(m.avg_holding_days, 0)}d`, false],
    ["Best / worst yr", `${pctSigned(m.best_year_pct ?? null, 0)} / ${pctSigned(m.worst_year_pct ?? null, 0)}`, false],
    ["Ann. turnover", `${num(m.annual_turnover_pct, 0)}%`, false],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cells.map(([label, val, signed]) => {
        const neg = signed && val.trim().startsWith("-");
        return (
          <div key={label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
            <span
              className={cn(
                "tabular-nums text-sm font-semibold",
                signed ? (neg ? "text-neg" : "text-pos") : "text-fg",
              )}
            >
              {val}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SplitCell({ label, s }: { label: string; s?: import("@/api/baskets").OosSegment }) {
  return (
    <div className="rounded bg-surface p-1.5">
      <p className="text-[9px] uppercase tracking-wide text-fg-faint">{label}</p>
      <p className={cn("font-semibold", (s?.return_pct ?? 0) < 0 ? "text-neg" : "text-pos")}>
        {pctSigned(s?.return_pct ?? null, 1)}
      </p>
      <p className="text-[10px] text-fg-faint">
        Sharpe {num(s?.sharpe_ratio, 2)} · vs bench {pctSigned(s?.benchmark_return_pct ?? null, 1)}
      </p>
    </div>
  );
}

function RegimeCell({ label, r }: { label: string; r?: import("@/api/baskets").RegimeSegment }) {
  return (
    <div className="rounded bg-surface p-1.5">
      <p className="text-[9px] uppercase tracking-wide text-fg-faint">
        {label} · {r?.days ?? 0}d
      </p>
      <p className={cn("font-semibold", (r?.return_pct ?? 0) < 0 ? "text-neg" : "text-pos")}>
        {pctSigned(r?.return_pct ?? null, 1)}
      </p>
      <p className="text-[10px] text-fg-faint">vol {num(r?.ann_vol_pct, 1)}%</p>
    </div>
  );
}

function RebalanceTable({ rows }: { rows: import("@/api/baskets").RebalanceSnapshot[] }) {
  const [open, setOpen] = useState(false);
  const shown = open ? rows : rows.slice(-6);
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-fg-faint">
          Rebalances ({rows.length})
        </p>
        {rows.length > 6 && (
          <button
            className="text-[11px] text-accent hover:underline"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Show last 6" : "Show all"}
          </button>
        )}
      </div>
      <div className="mt-1 overflow-x-auto rounded-md border border-line">
        <table className="w-full min-w-[520px] text-xs tabular-nums">
          <thead>
            <tr className="border-b border-line bg-surface text-fg-faint">
              <th className="px-2 py-1.5 text-left">Date</th>
              <th className="px-2 py-1.5 text-right">Portfolio</th>
              <th className="px-2 py-1.5 text-right">Orders</th>
              <th className="px-2 py-1.5 text-right">Turnover</th>
              <th className="px-2 py-1.5 text-right">Cash</th>
              <th className="px-2 py-1.5 text-left">Top holdings</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const top = Object.entries(r.weights)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([s, w]) => `${s} ${(w * 100).toFixed(0)}%`)
                .join(", ");
              return (
                <tr key={r.as_of} className="border-b border-line/60 last:border-0">
                  <td className="px-2 py-1 text-left">{r.as_of}</td>
                  <td className="px-2 py-1 text-right">{inrCompact(r.portfolio_value)}</td>
                  <td className="px-2 py-1 text-right">{r.n_orders}</td>
                  <td className="px-2 py-1 text-right">{r.turnover_pct.toFixed(1)}%</td>
                  <td className="px-2 py-1 text-right">{r.cash_pct.toFixed(1)}%</td>
                  <td className="px-2 py-1 text-left text-fg-muted">{top}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LivePanel({ live }: { live: import("@/api/baskets").BasketLiveStatus }) {
  return (
    <SectionCard
      title="Live (paper account)"
      index={1}
      actions={
        live.rebalance_due ? (
          <span className="rounded bg-amber-400/10 px-2 py-0.5 text-[11px] font-semibold text-amber-500">
            rebalance due
          </span>
        ) : null
      }
    >
      <div className="flex flex-col gap-3 p-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Portfolio value" value={inr(live.portfolio_value)} />
          <Stat
            label="Return"
            value={pctSigned(live.return_pct ?? null, 2)}
            tone={(live.return_pct ?? 0) < 0 ? "neg" : "pos"}
          />
          <Stat label="Invested" value={inr(live.invested_value)} />
          <Stat label="Cash" value={inr(live.basket_cash)} />
        </div>
        {live.holdings.length > 0 && (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[420px] text-xs tabular-nums">
              <thead>
                <tr className="border-b border-line bg-surface text-fg-faint">
                  <th className="px-2 py-1.5 text-left">Symbol</th>
                  <th className="px-2 py-1.5 text-right">Qty</th>
                  <th className="px-2 py-1.5 text-right">Price</th>
                  <th className="px-2 py-1.5 text-right">Value</th>
                  <th className="px-2 py-1.5 text-right">Weight</th>
                </tr>
              </thead>
              <tbody>
                {live.holdings.map((h) => (
                  <tr key={h.symbol} className="border-b border-line/60 last:border-0">
                    <td className="px-2 py-1 text-left font-medium text-fg">{h.symbol}</td>
                    <td className="px-2 py-1 text-right">{h.qty}</td>
                    <td className="px-2 py-1 text-right">{inr(h.price, 2)}</td>
                    <td className="px-2 py-1 text-right">{inrCompact(h.value)}</td>
                    <td className="px-2 py-1 text-right">{(h.weight * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "tabular-nums text-sm font-semibold",
          tone === "neg" ? "text-neg" : tone === "pos" ? "text-pos" : "text-fg",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function EditPanel({
  sleeves: initial,
  frequency: f0,
  driftBand: d0,
  capital: c0,
  benchmark: b0,
  saving,
  onCancel,
  onSave,
}: {
  sleeves: Sleeve[];
  frequency: Frequency;
  driftBand: number;
  capital: number;
  benchmark: string;
  saving: boolean;
  onCancel: () => void;
  onSave: (payload: {
    spec: { sleeves: Sleeve[] };
    rebalance_frequency: Frequency;
    drift_band_pct: number;
    capital: number;
    benchmark: string;
  }) => void;
}) {
  const [sleeves, setSleeves] = useState<Sleeve[]>(
    initial.map((sl) => ({
      ...sl,
      members: sl.members.map((m) => (m.includes(":") ? m : `NSE:${m}`)),
    })),
  );
  const [frequency, setFrequency] = useState<Frequency>(f0);
  const [driftBand, setDriftBand] = useState(d0);
  const [capital, setCapital] = useState(c0);
  const [benchmark, setBenchmark] = useState(b0);

  const total = sleeves.reduce((s, sl) => s + (Number(sl.weight_pct) || 0), 0);
  const ok = Math.abs(total - 100) < 0.5 && sleeves.every((sl) => sl.members.length > 0);

  return (
    <SectionCard title="Edit basket" index={0}>
      <div className="flex flex-col gap-4 p-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">Rebalance</span>
            <select
              className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
              value={frequency}
              onChange={(e) => setFrequency(e.target.value as Frequency)}
            >
              {(["weekly", "monthly", "quarterly"] as Frequency[]).map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">Drift band %</span>
            <Input type="number" value={driftBand} onChange={(e) => setDriftBand(Number(e.target.value))} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">Capital (₹)</span>
            <Input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">Benchmark</span>
            <Input value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
          </label>
        </div>

        <SleeveEditor sleeves={sleeves} onChange={setSleeves} />

        <div className="flex items-center gap-2">
          <Button
            disabled={!ok || saving}
            onClick={() =>
              onSave({
                spec: {
                  sleeves: sleeves.map((sl) => ({
                    ...sl,
                    members: sl.members.map((m) =>
                      (m.includes(":") ? m.split(":")[1] : m).toUpperCase(),
                    ),
                  })),
                },
                rebalance_frequency: frequency,
                drift_band_pct: driftBand,
                capital,
                benchmark,
              })
            }
          >
            {saving && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            Save changes
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
