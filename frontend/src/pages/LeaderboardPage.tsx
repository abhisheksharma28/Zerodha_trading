import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { LeaderboardRow } from "@/api/leaderboard";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useAdoptTuned,
  useCreatePaperDeployments,
  useLeaderboard,
  useLeaderboardDetail,
  useRefreshLeaderboard,
  useRunParamSim,
  useRunRobustness,
  useRunTuning,
} from "@/hooks/useLeaderboard";
import type { ParamSimBlock, RobustnessBlock, TuningDetail } from "@/api/leaderboard";
import { inr, inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const M = (r: LeaderboardRow, k: string): number | null =>
  (r.backtest?.metrics?.[k] as number | null | undefined) ?? null;

function numCell(v: number | null | undefined, suffix = "", digits = 2) {
  if (v == null) return <span className="text-fg-faint">—</span>;
  return (
    <span className={cn("tabular-nums", v < 0 && "text-neg", v > 0 && suffix === "%" && "text-pos")}>
      {num(v, digits)}
      {suffix}
    </span>
  );
}

export default function LeaderboardPage() {
  const { data, isLoading } = useLeaderboard();
  const refresh = useRefreshLeaderboard();
  const paper = useCreatePaperDeployments();
  const [openSlug, setOpenSlug] = useState<string | null>(null);

  const columns: Column<LeaderboardRow>[] = [
    {
      key: "rank",
      header: "#",
      align: "right",
      sortValue: (r) => r.rank ?? 999,
      cell: (r) => (r.rank ? <span className="font-semibold">{r.rank}</span> : "—"),
    },
    {
      key: "name",
      header: "Strategy",
      sortValue: (r) => r.name,
      cell: (r) => (
        <div>
          <Link
            to={`/strategy-library/${r.slug}`}
            className="font-medium text-fg hover:text-accent"
            onClick={(e) => e.stopPropagation()}
          >
            {r.name}
          </Link>
          <div className="text-[11px] text-fg-faint">
            {r.category}
            {r.canonical
              ? ` · ${r.canonical.universe_name} · ${r.canonical.timeframe} · ${r.canonical.years}y`
              : r.unsuited_reason
                ? " · manual pair config"
                : ""}
            {r.backtest?.ruined && <span className="ml-1 text-neg">· RUINED</span>}
            {r.backtest?.stale_config && <span className="ml-1 text-amber-500">· stale</span>}
          </div>
        </div>
      ),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      sortValue: (r) => r.composite_score ?? -1,
      cell: (r) =>
        r.composite_score == null ? (
          <span className="text-fg-faint">—</span>
        ) : (
          <span className="font-mono font-semibold tabular-nums">{num(r.composite_score, 1)}</span>
        ),
    },
    { key: "ret", header: "BT Return", align: "right", sortValue: (r) => M(r, "return_pct") ?? -1e9, cell: (r) => numCell(M(r, "return_pct"), "%") },
    { key: "cagr", header: "CAGR", align: "right", sortValue: (r) => M(r, "cagr_pct") ?? -1e9, cell: (r) => numCell(M(r, "cagr_pct"), "%") },
    { key: "sharpe", header: "Sharpe", align: "right", sortValue: (r) => M(r, "sharpe_ratio") ?? -1e9, cell: (r) => numCell(M(r, "sharpe_ratio")) },
    { key: "sortino", header: "Sortino", align: "right", sortValue: (r) => M(r, "sortino_ratio") ?? -1e9, cell: (r) => numCell(M(r, "sortino_ratio")) },
    { key: "mdd", header: "Max DD", align: "right", sortValue: (r) => M(r, "max_drawdown_pct") ?? 1e9, cell: (r) => numCell(M(r, "max_drawdown_pct"), "%") },
    { key: "trades", header: "Trades", align: "right", sortValue: (r) => M(r, "total_trades") ?? -1, cell: (r) => numCell(M(r, "total_trades"), "", 0) },
    { key: "win", header: "Win%", align: "right", sortValue: (r) => M(r, "win_rate_pct") ?? -1, cell: (r) => numCell(M(r, "win_rate_pct"), "%", 1) },
    {
      key: "robust",
      header: "Robust",
      align: "right",
      sortValue: (r) => r.robustness?.robustness_score ?? -1,
      cell: (r) => {
        const rb = r.robustness;
        if (!rb) return <span className="text-fg-faint">—</span>;
        const flags: string[] = [];
        if (rb.monte_carlo.bootstrap?.prob_ruin) flags.push("ruin");
        if (rb.sensitivity.overfit_risk) flags.push("overfit");
        if ((rb.walk_forward.sharpe_decay ?? 0) > 0.3) flags.push("decay");
        return (
          <div className="text-right text-[11px]">
            <span
              className={cn(
                "font-mono font-semibold tabular-nums",
                rb.robustness_score < 40 ? "text-neg" : rb.robustness_score < 70 ? "text-amber-500" : "text-pos",
              )}
            >
              {num(rb.robustness_score, 0)}
            </span>
            {flags.length > 0 && <div className="text-neg">{flags.join(" · ")}</div>}
          </div>
        );
      },
    },
    {
      key: "paper",
      header: "Paper (live)",
      align: "right",
      sortValue: (r) => r.live?.sharpe_daily_ann ?? -1e9,
      cell: (r) => {
        const l = r.live;
        if (!l) return <span className="text-fg-faint">—</span>;
        if (!l.available)
          return (
            <span className="text-[11px] text-fg-faint">
              collecting · {l.days_live}d
            </span>
          );
        return (
          <div className="text-right text-[11px]">
            <div className={cn("tabular-nums", (l.realised_pnl ?? 0) < 0 ? "text-neg" : "text-pos")}>
              {inrCompact(l.realised_pnl)} · Sh {num(l.sharpe_daily_ann, 2)}
            </div>
            <div className="text-fg-faint">
              {l.closed_trades} trades · {l.days_live}d
            </div>
          </div>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Strategy Leaderboard"
        subtitle="Standardised backtest (NIFTY 100, 3y) + live paper-trading performance. Research only — not advice."
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={refresh.isPending}
          onClick={() => {
            if (
              window.confirm(
                "Re-run every canonical backtest (NIFTY 100 × 3 years each). This is slow — minutes — and runs synchronously. Continue?",
              )
            )
              refresh.mutate(undefined);
          }}
        >
          {refresh.isPending ? "Refreshing backtests…" : "Refresh backtests"}
        </Button>
        <Button
          variant="outline"
          disabled={paper.isPending}
          onClick={() => paper.mutate()}
        >
          {paper.isPending ? "Starting…" : "Start paper tracking"}
        </Button>
        {data && (
          <span className="text-xs text-fg-faint">
            updated {new Date(data.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {refresh.data && (
        <Card>
          <CardContent className="p-3 text-xs">
            {Object.entries(refresh.data).map(([slug, status]) => (
              <div key={slug} className="flex gap-2">
                <span className="w-56 shrink-0 font-mono">{slug}</span>
                <span className={cn(status.startsWith("error") ? "text-neg" : "text-fg-muted")}>
                  {status}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {paper.data && (
        <p className="text-xs text-fg-muted">
          Paper deployments:{" "}
          {Object.entries(paper.data)
            .map(([s, v]) => `${s}: ${v}`)
            .join(" · ")}
        </p>
      )}

      {isLoading ? (
        <p className="py-16 text-center text-sm text-fg-faint">Loading…</p>
      ) : !data ? (
        <p className="py-16 text-center text-sm text-fg-faint">No leaderboard data.</p>
      ) : (
        <>
          {!data.any_backtest_cached && (
            <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm text-amber-300 light:text-amber-700">
              No canonical backtests have been run yet. Click “Refresh backtests” to populate the
              ranking (this takes several minutes).
            </p>
          )}
          <Card>
            <CardContent className="p-0">
              <DataTable
                columns={columns}
                rows={data.rows}
                rowKey={(r) => r.slug}
                onRowClick={(r) => setOpenSlug((s) => (s === r.slug ? null : r.slug))}
                initialSort={{ key: "score", dir: "desc" }}
              />
            </CardContent>
          </Card>

          {openSlug && <DetailPanel slug={openSlug} />}

          <p className="text-xs leading-relaxed text-fg-faint">{data.score_method}</p>
        </>
      )}
    </div>
  );
}

function DetailPanel({ slug }: { slug: string }) {
  const { data, isLoading, isError, error } = useLeaderboardDetail(slug);
  const runRob = useRunRobustness();
  const runTune = useRunTuning();
  const adopt = useAdoptTuned();
  const runSim = useRunParamSim();

  if (isLoading) return <p className="text-sm text-fg-faint">Loading {slug}…</p>;
  if (isError)
    return (
      <Card>
        <CardContent className="p-4 text-sm text-fg-muted">
          {(error as Error).message}
        </CardContent>
      </Card>
    );
  if (!data) return null;

  const equity = data.equity_curve.map(([ts, v]) => ({ t: ts.slice(0, 10), v: Math.round(v) }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {slug} — {data.config.universe_name} · {data.config.timeframe} · {data.config.years}y ·{" "}
          {data.config.preset}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {data.ruined && (
          <p className="text-sm text-neg">
            Ruined — the book hit zero equity; the {data.config.max_gross_exposure}x exposure cap was
            not enough for this preset on this universe. Peak exposure{" "}
            {num(data.peak_gross_exposure_pct ?? 0, 0)}% of capital.
          </p>
        )}

        {equity.length > 1 && (
          <div className="h-52 w-full">
            <ResponsiveContainer>
              <AreaChart data={equity} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                <defs>
                  <linearGradient id="lbeq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={48} />
                <YAxis
                  tick={{ fontSize: 10 }}
                  width={64}
                  tickFormatter={(v) => inrCompact(v as number)}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  formatter={(v) => inr(v as number)}
                  contentStyle={{
                    background: "var(--color-surface)",
                    border: "1px solid var(--color-line-strong)",
                    fontSize: 12,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="v"
                  stroke="var(--color-accent)"
                  strokeWidth={1.5}
                  fill="url(#lbeq)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <SymTable title="Top symbols" rows={data.top_symbols} />
          <SymTable title="Worst symbols" rows={data.bottom_symbols} />
        </div>

        <RobustnessSection
          slug={slug}
          rob={data.robustness}
          running={runRob.isPending && runRob.variables === slug}
          onRun={() => {
            if (
              window.confirm(
                "Run the robustness suite (walk-forward + Monte Carlo + parameter sweep)? This runs ~13 backtests and takes several minutes.",
              )
            )
              runRob.mutate(slug);
          }}
          error={runRob.isError && runRob.variables === slug ? (runRob.error as Error).message : null}
        />

        <TuningSection
          slug={slug}
          tuning={data.tuning}
          running={runTune.isPending && runTune.variables === slug}
          adopting={adopt.isPending}
          onRun={() => {
            if (
              window.confirm(
                "Run the tuning grid? Each grid point is scored on the worse of its in-sample / out-of-sample Sharpe. Several minutes.",
              )
            )
              runTune.mutate(slug);
          }}
          onAdopt={(overrides) => adopt.mutate({ slug, overrides })}
          error={
            runTune.isError && runTune.variables === slug ? (runTune.error as Error).message : null
          }
        />

        <ParamSimSection
          slug={slug}
          sim={data.param_sim}
          running={runSim.isPending && runSim.variables === slug}
          onRun={() => {
            if (
              window.confirm(
                "Re-run the canonical backtest ~30 times with every numeric parameter jittered ±5%? Several minutes.",
              )
            )
              runSim.mutate(slug);
          }}
          error={runSim.isError && runSim.variables === slug ? (runSim.error as Error).message : null}
        />

        {data.skipped.length > 0 && (
          <p className="text-xs text-amber-500">
            Skipped {data.skipped.length}: {data.skipped.slice(0, 12).map((s) => s.symbol).join(", ")}
            {data.skipped.length > 12 ? "…" : ""}
          </p>
        )}
        <details className="text-xs text-fg-faint">
          <summary className="cursor-pointer">Caveats</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {data.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </details>
      </CardContent>
    </Card>
  );
}

function SymTable({ title, rows }: { title: string; rows: { symbol: string; trades: number; net_pnl: number; win_rate_pct: number }[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-fg-muted">{title}</div>
      <table className="w-full text-left text-xs">
        <thead className="text-fg-faint">
          <tr>
            <th className="py-1 pr-3">Symbol</th>
            <th className="py-1 pr-3">Trades</th>
            <th className="py-1 pr-3">Win%</th>
            <th className="py-1">Net P&L</th>
          </tr>
        </thead>
        <tbody className="text-fg-muted">
          {rows.map((s) => (
            <tr key={s.symbol} className="border-t border-line">
              <td className="py-1 pr-3 font-mono text-[11px]">{s.symbol}</td>
              <td className="py-1 pr-3">{s.trades}</td>
              <td className="py-1 pr-3">{num(s.win_rate_pct, 0)}%</td>
              <td className={cn("py-1 tabular-nums", s.net_pnl < 0 ? "text-neg" : "text-pos")}>
                {inr(s.net_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Kv({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" | "warn" }) {
  return (
    <div className="rounded-md border border-line bg-elevated px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div
        className={cn(
          "font-mono text-sm tabular-nums",
          tone === "pos" && "text-pos",
          tone === "neg" && "text-neg",
          tone === "warn" && "text-amber-500",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function RobustnessSection({
  slug,
  rob,
  running,
  onRun,
  error,
}: {
  slug: string;
  rob: RobustnessBlock | null;
  running: boolean;
  onRun: () => void;
  error: string | null;
}) {
  return (
    <div className="rounded-lg border border-line-strong bg-surface p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">
          Robustness
          {rob && (
            <span
              className={cn(
                "ml-2 font-mono",
                rob.robustness_score < 40
                  ? "text-neg"
                  : rob.robustness_score < 70
                    ? "text-amber-500"
                    : "text-pos",
              )}
            >
              {num(rob.robustness_score, 0)}/100
            </span>
          )}
        </span>
        <Button variant="outline" disabled={running} onClick={onRun}>
          {running ? "Running suite…" : rob ? "Re-run suite" : "Run robustness suite"}
        </Button>
      </div>
      {error && <p className="text-xs text-neg">{error}</p>}

      {!rob ? (
        <p className="text-xs text-fg-faint">
          Not run yet for {slug}. The suite runs ~13 backtests (walk-forward folds + a parameter
          sweep) plus Monte Carlo on the realised trades — several minutes.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-fg-muted">
            {rob.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>

          {rob.monte_carlo.available && rob.monte_carlo.bootstrap && (
            <div>
              <div className="mb-1 text-xs font-semibold text-fg-muted">
                Monte Carlo · {rob.monte_carlo.n_sims?.toLocaleString()} resamples of{" "}
                {rob.monte_carlo.n_trades} trades
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kv
                  label="Return p5 / p50 / p95"
                  value={`${num(rob.monte_carlo.bootstrap.return_pct.p5 ?? 0, 0)} / ${num(
                    rob.monte_carlo.bootstrap.return_pct.p50,
                    0,
                  )} / ${num(rob.monte_carlo.bootstrap.return_pct.p95, 0)}%`}
                />
                <Kv
                  label="P(lose money)"
                  value={`${num(rob.monte_carlo.bootstrap.prob_loss * 100, 1)}%`}
                  tone={rob.monte_carlo.bootstrap.prob_loss > 0.5 ? "warn" : undefined}
                />
                <Kv
                  label="P(ruin)"
                  value={`${num(rob.monte_carlo.bootstrap.prob_ruin * 100, 2)}%`}
                  tone={rob.monte_carlo.bootstrap.prob_ruin > 0 ? "neg" : "pos"}
                />
                <Kv
                  label={`P(DD > ${num(rob.monte_carlo.dd_threshold_pct ?? 20, 0)}%)`}
                  value={`${num(rob.monte_carlo.bootstrap.prob_dd_beyond_threshold * 100, 1)}%`}
                />
                <Kv
                  label="Max DD p50 / p95"
                  value={`${num(rob.monte_carlo.bootstrap.max_dd_pct.p50, 1)} / ${num(
                    rob.monte_carlo.bootstrap.max_dd_pct.p95,
                    1,
                  )}%`}
                />
                <Kv
                  label="Actual return / DD"
                  value={`${num(rob.monte_carlo.actual_return_pct ?? 0, 1)}% / ${num(
                    rob.monte_carlo.actual_max_dd_pct ?? 0,
                    1,
                  )}%`}
                />
              </div>
            </div>
          )}

          {rob.walk_forward.available && (
            <div>
              <div className="mb-1 text-xs font-semibold text-fg-muted">
                Walk-forward · {rob.walk_forward.oos_profitable_folds}/{rob.walk_forward.total_folds}{" "}
                OOS folds profitable
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kv label="IS Sharpe (mean)" value={num(rob.walk_forward.is_sharpe_mean ?? 0, 2)} />
                <Kv
                  label="OOS Sharpe (mean)"
                  value={num(rob.walk_forward.oos_sharpe_mean ?? 0, 2)}
                  tone={(rob.walk_forward.oos_sharpe_mean ?? 0) < 0 ? "neg" : undefined}
                />
                <Kv
                  label="Sharpe decay"
                  value={num(rob.walk_forward.sharpe_decay ?? 0, 2)}
                  tone={(rob.walk_forward.sharpe_decay ?? 0) > 0.3 ? "warn" : undefined}
                />
                <Kv
                  label="WF efficiency"
                  value={
                    rob.walk_forward.walk_forward_efficiency == null
                      ? "—"
                      : num(rob.walk_forward.walk_forward_efficiency, 2)
                  }
                />
              </div>
              {rob.walk_forward.folds && (
                <table className="mt-2 w-full text-left text-[11px]">
                  <thead className="text-fg-faint">
                    <tr>
                      <th className="py-1 pr-3">Fold (OOS window)</th>
                      <th className="py-1 pr-3">IS ret / Sharpe</th>
                      <th className="py-1">OOS ret / Sharpe</th>
                    </tr>
                  </thead>
                  <tbody className="text-fg-muted">
                    {rob.walk_forward.folds.map((f) => (
                      <tr key={f.fold} className="border-t border-line">
                        <td className="py-1 pr-3">
                          {f.oos_start} → {f.oos_end}
                        </td>
                        <td className="py-1 pr-3 tabular-nums">
                          {num((f.is_metrics?.return_pct as number) ?? 0, 1)}% /{" "}
                          {num((f.is_metrics?.sharpe_ratio as number) ?? 0, 2)}
                        </td>
                        <td
                          className={cn(
                            "py-1 tabular-nums",
                            ((f.oos_metrics?.return_pct as number) ?? 0) < 0
                              ? "text-neg"
                              : "text-pos",
                          )}
                        >
                          {num((f.oos_metrics?.return_pct as number) ?? 0, 1)}% /{" "}
                          {num((f.oos_metrics?.sharpe_ratio as number) ?? 0, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {rob.sensitivity.available && rob.sensitivity.surface && (
            <div>
              <div className="mb-1 text-xs font-semibold text-fg-muted">
                Parameter sensitivity · <span className="font-mono">{rob.sensitivity.param}</span>
                {rob.sensitivity.overfit_risk ? (
                  <span className="ml-2 text-neg">overfit risk — preset is a lone spike</span>
                ) : (
                  <span className="ml-2 text-pos">plateau — robust</span>
                )}
              </div>
              <table className="w-full text-left text-[11px]">
                <thead className="text-fg-faint">
                  <tr>
                    <th className="py-1 pr-3">{rob.sensitivity.param}</th>
                    <th className="py-1 pr-3">Sharpe</th>
                    <th className="py-1 pr-3">Return</th>
                    <th className="py-1">Max DD</th>
                  </tr>
                </thead>
                <tbody className="text-fg-muted">
                  {rob.sensitivity.surface.map((p) => (
                    <tr
                      key={p.value}
                      className={cn(
                        "border-t border-line",
                        p.value === rob.sensitivity.preset_value && "font-semibold text-fg",
                      )}
                    >
                      <td className="py-1 pr-3 font-mono">
                        {p.value}
                        {p.value === rob.sensitivity.preset_value && " (preset)"}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">{num(p.sharpe, 2)}</td>
                      <td className="py-1 pr-3 tabular-nums">{num(p.return_pct, 1)}%</td>
                      <td className="py-1 tabular-nums">{num(p.max_dd_pct, 1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const VERDICT_LABEL: Record<string, { text: string; cls: string }> = {
  recommend_tuned: { text: "Tuned combo recommended", cls: "text-pos" },
  keep_preset: { text: "Keep the current preset", cls: "text-fg-muted" },
  no_eligible_combo: { text: "No eligible combo", cls: "text-amber-500" },
};

function ovStr(o: Record<string, unknown> | null | undefined) {
  if (!o || Object.keys(o).length === 0) return "—";
  return Object.entries(o)
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
}

function TuningSection({
  slug,
  tuning,
  running,
  adopting,
  onRun,
  onAdopt,
  error,
}: {
  slug: string;
  tuning: TuningDetail | null;
  running: boolean;
  adopting: boolean;
  onRun: () => void;
  onAdopt: (overrides: Record<string, unknown> | null) => void;
  error: string | null;
}) {
  const v = tuning ? VERDICT_LABEL[tuning.verdict] : null;
  return (
    <div className="rounded-lg border border-line-strong bg-surface p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">
          Preset tuning{" "}
          {v && <span className={cn("ml-2 text-xs font-normal", v.cls)}>{v.text}</span>}
        </span>
        <Button variant="outline" disabled={running} onClick={onRun}>
          {running ? "Running grid…" : tuning ? "Re-run grid" : "Run tuning grid"}
        </Button>
      </div>
      {error && <p className="text-xs text-neg">{error}</p>}

      {!tuning ? (
        <p className="text-xs text-fg-faint">
          Not run yet for {slug}. Grid-searches ~2 parameters, scoring each point on the worse of
          its in-sample / out-of-sample Sharpe — so an in-sample-only spike can't win.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-fg-muted">{tuning.explanation}</p>

          <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
            <Kv label="Preset params" value={ovStr(tuning.preset_params)} />
            <Kv
              label="Recommended overrides"
              value={ovStr(tuning.recommended_overrides)}
              tone={tuning.recommended_overrides ? "pos" : undefined}
            />
            <Kv
              label="Currently adopted"
              value={ovStr(tuning.currently_adopted)}
              tone={tuning.currently_adopted ? "warn" : undefined}
            />
          </div>

          {tuning.verdict === "recommend_tuned" && tuning.recommended_overrides && (
            <div className="flex gap-2">
              <Button
                disabled={adopting}
                onClick={() => onAdopt(tuning.recommended_overrides)}
              >
                {adopting ? "Adopting…" : "Adopt tuned preset"}
              </Button>
              <span className="self-center text-[11px] text-fg-faint">
                Applied on the next “Refresh backtests” and to new paper deployments.
              </span>
            </div>
          )}
          {tuning.currently_adopted && (
            <Button variant="outline" disabled={adopting} onClick={() => onAdopt(null)}>
              {adopting ? "Clearing…" : "Clear adopted overrides"}
            </Button>
          )}

          <table className="w-full text-left text-[11px]">
            <thead className="text-fg-faint">
              <tr>
                <th className="py-1 pr-3">Params</th>
                <th className="py-1 pr-3">IS Sharpe / ret</th>
                <th className="py-1 pr-3">OOS Sharpe / ret</th>
                <th className="py-1 pr-3">OOS trades</th>
                <th className="py-1">Robust score</th>
              </tr>
            </thead>
            <tbody className="text-fg-muted">
              {tuning.surface
                .slice()
                .sort((a, b) => (b.robust_score ?? -1e9) - (a.robust_score ?? -1e9))
                .map((r, i) => (
                  <tr
                    key={i}
                    className={cn(
                      "border-t border-line",
                      r.is_preset && "font-semibold text-fg",
                    )}
                  >
                    <td className="py-1 pr-3 font-mono">
                      {ovStr(r.params)}
                      {r.is_preset && " (preset)"}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">
                      {num(r.is_sharpe, 2)} / {num(r.is_return_pct, 1)}%
                    </td>
                    <td
                      className={cn(
                        "py-1 pr-3 tabular-nums",
                        r.oos_sharpe < 0 ? "text-neg" : "text-pos",
                      )}
                    >
                      {num(r.oos_sharpe, 2)} / {num(r.oos_return_pct, 1)}%
                    </td>
                    <td className="py-1 pr-3 tabular-nums">{r.oos_trades}</td>
                    <td className="py-1 tabular-nums">
                      {r.ruined ? (
                        <span className="text-neg">ruined</span>
                      ) : r.robust_score == null ? (
                        <span className="text-fg-faint">ineligible</span>
                      ) : (
                        num(r.robust_score, 2)
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const SIM_KPIS: { key: string; label: string; suffix?: string; digits?: number; lowerBetter?: boolean }[] = [
  { key: "return_pct", label: "Return", suffix: "%", digits: 1 },
  { key: "cagr_pct", label: "CAGR", suffix: "%", digits: 1 },
  { key: "sharpe_ratio", label: "Sharpe", digits: 2 },
  { key: "sortino_ratio", label: "Sortino", digits: 2 },
  { key: "max_drawdown_pct", label: "Max DD", suffix: "%", digits: 1, lowerBetter: true },
  { key: "calmar_ratio", label: "Calmar", digits: 2 },
  { key: "win_rate_pct", label: "Win %", suffix: "%", digits: 1 },
  { key: "profit_factor", label: "Profit factor", digits: 2 },
  { key: "total_trades", label: "Trades", digits: 0 },
];

function ParamSimSection({
  slug,
  sim,
  running,
  onRun,
  error,
}: {
  slug: string;
  sim: ParamSimBlock | null;
  running: boolean;
  onRun: () => void;
  error: string | null;
}) {
  return (
    <div className="rounded-lg border border-line-strong bg-surface p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">
          Parameter stability
          {sim && (
            <span
              className={cn(
                "ml-2 text-xs font-normal",
                sim.verdict === "fragile" ? "text-neg" : "text-pos",
              )}
            >
              ±{sim.pct}% neighbourhood — {sim.verdict}
            </span>
          )}
        </span>
        <Button variant="outline" disabled={running} onClick={onRun}>
          {running ? "Simulating…" : sim ? "Re-run ±5% sim" : "Run ±5% param sim"}
        </Button>
      </div>
      {error && <p className="text-xs text-neg">{error}</p>}

      {!sim ? (
        <p className="text-xs text-fg-faint">
          Not run yet for {slug}. Re-runs the canonical backtest ~30 times with every numeric
          parameter independently jittered within ±5%, then shows the KPI spread — a tight spread
          around the base result = robust; a wide one = knife-edge.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-fg-muted">
            {sim.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <p className="text-[11px] text-fg-faint">
            {sim.n_samples} samples · jittered: {sim.perturbed_params.join(", ")}
            {sim.ruined_fraction > 0 && (
              <span className="ml-1 text-neg">· {Math.round(sim.ruined_fraction * 100)}% ruined</span>
            )}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-fg-faint">
                <tr>
                  <th className="py-1 pr-3">KPI</th>
                  <th className="py-1 pr-3">Base</th>
                  <th className="py-1 pr-3">p5</th>
                  <th className="py-1 pr-3">Median</th>
                  <th className="py-1 pr-3">p95</th>
                  <th className="py-1">Std</th>
                </tr>
              </thead>
              <tbody className="text-fg-muted">
                {SIM_KPIS.map(({ key, label, suffix = "", digits = 2 }) => {
                  const d = sim.distribution[key];
                  const base = sim.base[key];
                  if (!d) return null;
                  const outOfBand = base < d.p5 || base > d.p95;
                  return (
                    <tr key={key} className="border-t border-line">
                      <td className="py-1 pr-3">{label}</td>
                      <td
                        className={cn(
                          "py-1 pr-3 font-semibold tabular-nums",
                          outOfBand && "text-neg",
                        )}
                      >
                        {num(base, digits)}
                        {suffix}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">
                        {num(d.p5, digits)}
                        {suffix}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">
                        {num(d.p50, digits)}
                        {suffix}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">
                        {num(d.p95, digits)}
                        {suffix}
                      </td>
                      <td className="py-1 tabular-nums">{num(d.std, digits)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
