import { Fragment, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2, RefreshCw } from "lucide-react";

import type {
  MonthRankingRow,
  SeasonalSignal,
  SeasonCell,
  WalkForwardResult,
} from "@/api/seasonality";
import { STRATEGY_LABELS } from "@/api/seasonality";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import {
  useFreezeModel,
  useGenerateSignal,
  useModelVersions,
  useRefreshSeasonality,
  useReviewSignal,
  useSeasonalityBacktest,
  useSeasonalityReport,
  useSeasonalSignals,
  useSeasonalityStatus,
} from "@/hooks/useSeasonality";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (s: string) => s.replace(/^NIFTY /, "");

const BUCKET_CLS: Record<string, string> = {
  dark_green: "bg-pos/30 text-pos font-semibold",
  green: "bg-pos/15 text-pos",
  light_green: "bg-pos/[0.06] text-fg-muted",
  gray: "text-fg-faint",
  light_red: "bg-neg/[0.06] text-fg-muted",
  red: "bg-neg/15 text-neg",
  dark_red: "bg-neg/30 text-neg font-semibold",
};

export default function SeasonalityPage() {
  const { data, isLoading } = useSeasonalityReport();
  const refresh = useRefreshSeasonality();
  const running = useSeasonalityStatus().data?.state === "running" || refresh.isPending;

  const sectors = useMemo(() => (data?.sectors ? [...data.sectors].sort() : []), [data]);
  const [openCell, setOpenCell] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Sector Seasonality"
        subtitle="A research-grade rebuild: maximum available history per sector, three edge measures, Benjamini-Hochberg FDR across the whole grid, bootstrap, multi-horizon stability, market-regime conditioning, and a strictly out-of-sample walk-forward backtest."
        actions={
          <Button
            size="sm"
            variant="outline"
            disabled={running}
            onClick={() => refresh.mutate()}
          >
            {running ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            {running ? "Rebuilding…" : "Rebuild"}
          </Button>
        }
      />

      {isLoading && <p className="py-10 text-center text-sm text-fg-faint">Loading…</p>}

      {data && !data.available && (
        <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-600 dark:text-amber-400">
          {data.reason} {running && "Rebuild in progress — this takes about a minute."}
        </div>
      )}

      {data?.available && (
        <>
          {/* 0 — VERDICT */}
          <div
            className={cn(
              "rounded-lg border p-4",
              data.verdict === "NO VALID EDGE FOUND"
                ? "border-amber-400/40 bg-amber-400/10"
                : "border-pos/40 bg-pos/10",
            )}
          >
            <p className="text-sm font-semibold text-fg">{data.verdict}</p>
            <p className="mt-1 max-w-3xl text-[13px] text-fg-muted">{data.verdict_detail}</p>
            <p className="mt-2 text-[11px] text-fg-faint">
              {data.sector_count} sectors · history {data.history_span?.earliest} →{" "}
              {data.history_span?.latest} · {data.fdr?.n_tested} hypotheses tested ·{" "}
              {data.fdr?.n_significant_q05} significant at q&lt;0.05 ·{" "}
              {data.fdr?.n_significant_q10} at q&lt;0.10
              {data.built_at && ` · built ${new Date(data.built_at).toLocaleString("en-IN")}`}
            </p>
          </div>

          {/* 1 — METHODOLOGY */}
          <SectionCard title="Methodology" index={1}>
            <p className="p-4 text-[13px] leading-relaxed text-fg-muted">{data.method}</p>
          </SectionCard>

          {/* 2 — CURRENT-MONTH OPPORTUNITY */}
          {data.current_month && (
            <SectionCard
              title={`This month — ${data.current_month.name}${
                data.current_month.anchor ? ` · ${data.current_month.anchor}` : ""
              }`}
              index={2}
            >
              <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
                <CandidateList
                  title="Strongest — potential long"
                  rows={data.current_month.long_candidates}
                  tone="pos"
                />
                <CandidateList
                  title="Weakest — potential short"
                  rows={data.current_month.short_candidates}
                  tone="neg"
                />
              </div>
              <p className="px-4 pb-3 text-[11px] text-fg-faint">
                Descriptive historical tilt, not a validated signal — see the verdict above and
                the backtest below.
              </p>
            </SectionCard>
          )}

          {/* 3 & 4 — MONTH-BY-MONTH BEST / WORST */}
          <MonthGrids report={data} />

          {/* 5 & 6 — FULL MATRIX + HEATMAP */}
          <SectionCard title="Full sector × month matrix — seasonal edge %, FDR-graded" index={5}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-xs tabular-nums">
                <thead>
                  <tr className="border-b border-line bg-surface">
                    <th className="px-2 py-1.5 text-left font-semibold text-fg-faint">Sector</th>
                    {MONTHS.map((m) => (
                      <th key={m} className="px-1.5 py-1.5 text-right font-semibold text-fg-faint">
                        {m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sectors.map((sec) => {
                    const row = data.grid?.[sec] ?? {};
                    return (
                      <Fragment key={sec}>
                        <tr className="border-b border-line/60">
                          <td className="whitespace-nowrap px-2 py-1 text-left text-fg-muted">
                            {short(sec)}
                          </td>
                          {MONTHS.map((_m, i) => {
                            const c = row[String(i + 1)];
                            const id = `${sec}-${i + 1}`;
                            if (!c)
                              return (
                                <td key={i} className="px-1.5 py-1 text-right text-fg-faint">
                                  ·
                                </td>
                              );
                            return (
                              <td
                                key={i}
                                onClick={() => setOpenCell(openCell === id ? null : id)}
                                className={cn(
                                  "cursor-pointer px-1.5 py-1 text-right",
                                  BUCKET_CLS[c.visual ?? "gray"],
                                  openCell === id && "ring-1 ring-inset ring-accent",
                                )}
                                title={`t ${num(c.t_stat, 2)} · q ${num(c.q_value ?? null, 3)} · n ${c.n} · ${c.t_label}`}
                              >
                                {c.mean_edge_pct >= 0 ? "+" : ""}
                                {num(c.mean_edge_pct, 1)}
                              </td>
                            );
                          })}
                        </tr>
                        {openCell?.startsWith(`${sec}-`) &&
                          row[openCell.split("-").pop() as string] && (
                            <tr>
                              <td colSpan={13} className="bg-bg/40 p-0">
                                <CellDetail cell={row[openCell.split("-").pop() as string]} />
                              </td>
                            </tr>
                          )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap gap-3 px-3 py-2 text-[10px] text-fg-faint">
              <Legend cls="bg-pos/30" label="positive · survives FDR" />
              <Legend cls="bg-pos/15" label="positive · significant" />
              <Legend cls="bg-pos/[0.06]" label="positive · weak" />
              <Legend cls="" label="no evidence (|t|<1)" />
              <Legend cls="bg-neg/[0.06]" label="negative · weak" />
              <Legend cls="bg-neg/15" label="negative · significant" />
              <Legend cls="bg-neg/30" label="negative · survives FDR" />
              <span>Click any cell for the full stat sheet.</span>
            </div>
          </SectionCard>

          {/* 7 — STATISTICAL VALIDATION */}
          <SectionCard title="Statistical validation" index={7}>
            <div className="p-4 text-[13px] text-fg-muted">
              <p>
                Across {data.fdr?.n_tested} sector×month hypotheses, Benjamini-Hochberg FDR leaves{" "}
                <b className="text-fg">{data.fdr?.n_significant_q05}</b> significant at q&lt;0.05 and{" "}
                <b className="text-fg">{data.fdr?.n_significant_q10}</b> at q&lt;0.10.
              </p>
              {data.fdr_survivors && data.fdr_survivors.length > 0 ? (
                <ul className="mt-2 list-disc space-y-0.5 pl-5">
                  {data.fdr_survivors.map((s, i) => (
                    <li key={i}>
                      {short(s.sector)} · {s.month_name} — edge {num(s.mean_edge_pct, 2)}% (
                      {s.direction}), q {num(s.q_value, 3)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-fg-faint">
                  Nothing clears the multiple-testing gate. The strongest raw signals (|t| up to
                  ~2.7) are consistent with noise across a grid this size.
                </p>
              )}
            </div>
          </SectionCard>

          {/* 8 — DATA-QUALITY AUDIT */}
          <SectionCard title="Data-quality audit" index={8}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-xs tabular-nums">
                <thead>
                  <tr className="border-b border-line bg-surface text-fg-faint">
                    <th className="px-2 py-1.5 text-left">Sector</th>
                    <th className="px-2 py-1.5 text-left">Status</th>
                    <th className="px-2 py-1.5 text-right">History</th>
                    <th className="px-2 py-1.5 text-right">Months</th>
                    <th className="px-2 py-1.5 text-right">Data start</th>
                    <th className="px-2 py-1.5 text-left">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(data.data_audit ?? {})
                    .filter((a) => a.sector.startsWith("NIFTY") && a.sector !== "NIFTY 50")
                    .sort((a, b) => a.sector.localeCompare(b.sector))
                    .map((a) => (
                      <tr key={a.sector} className="border-b border-line/50">
                        <td className="px-2 py-1 text-left text-fg-muted">{short(a.sector)}</td>
                        <td className="px-2 py-1 text-left">
                          <span
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                              a.status === "PASS"
                                ? "bg-pos/10 text-pos"
                                : a.status === "WARN"
                                  ? "bg-amber-400/10 text-amber-500"
                                  : "bg-neg/10 text-neg",
                            )}
                          >
                            {a.status}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-right">{num(a.years_available, 1)}y</td>
                        <td className="px-2 py-1 text-right">{a.complete_months}</td>
                        <td className="px-2 py-1 text-right">{a.data_start}</td>
                        <td className="px-2 py-1 text-left text-fg-faint">
                          {a.issues.slice(0, 1).join("; ") || "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {/* 9 — BACKTEST */}
          <BacktestPanel />

          {/* 10 — MODEL FREEZE + PROSPECTIVE SIGNALS */}
          <VersionsPanel canFreeze={!!data.available} />
        </>
      )}
    </div>
  );
}

function VersionsPanel({ canFreeze }: { canFreeze: boolean }) {
  const { data: versions = [] } = useModelVersions();
  const { data: signals = [] } = useSeasonalSignals();
  const freeze = useFreezeModel();
  const genSignal = useGenerateSignal();
  const review = useReviewSignal();
  const [ver, setVer] = useState("v1.0");

  return (
    <SectionCard title="Model freeze & prospective signals" index={10}>
      <div className="flex flex-col gap-4 p-4">
        <p className="text-[13px] text-fg-muted">
          Freeze the current methodology + parameters + report as a named version. A frozen
          model is never mutated by live results; each month it emits one immutable signal
          snapshot that can be reviewed once the month completes (predicted vs actual, rank IC).
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <input
            className="h-8 w-28 rounded border border-line bg-surface px-2 text-sm tabular-nums"
            value={ver}
            onChange={(e) => setVer(e.target.value)}
            placeholder="v1.0"
          />
          <Button
            size="sm"
            disabled={!canFreeze || freeze.isPending}
            onClick={() =>
              freeze.mutate({ version: ver, name: `Seasonality ${ver}` })
            }
          >
            {freeze.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
            Freeze current model
          </Button>
          {freeze.isError && (
            <span className="text-xs text-neg">
              {(freeze.error as { response?: { data?: { message?: string } } })?.response?.data
                ?.message ?? "Freeze failed"}
            </span>
          )}
        </div>

        {versions.length === 0 ? (
          <p className="text-xs text-fg-faint">No frozen versions yet.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {versions.map((v) => {
              const vSignals = signals.filter((s: SeasonalSignal) => s.model_version_id === v.id);
              return (
                <div key={v.id} className="rounded-md border border-line/70 bg-bg/40 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="text-sm font-semibold text-fg">{v.version}</span>
                      <span className="ml-2 text-xs text-fg-faint">{v.name}</span>
                      <span
                        className={cn(
                          "ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                          v.status === "frozen"
                            ? "bg-pos/10 text-pos"
                            : "bg-elevated text-fg-faint",
                        )}
                      >
                        {v.status}
                      </span>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={genSignal.isPending}
                      onClick={() => genSignal.mutate({ versionId: v.id })}
                    >
                      Generate next-month signal
                    </Button>
                  </div>
                  <p className="mt-1 text-[11px] text-fg-faint">
                    frozen {v.frozen_at ? new Date(v.frozen_at).toLocaleDateString("en-IN") : "—"} ·
                    hash {v.methodology_hash} · verdict: {v.verdict}
                  </p>

                  {vSignals.length > 0 && (
                    <div className="mt-2 overflow-x-auto">
                      <table className="w-full min-w-[560px] text-[11px] tabular-nums">
                        <thead>
                          <tr className="border-b border-line/60 text-fg-faint">
                            <th className="px-1.5 py-1 text-left">Signal</th>
                            <th className="px-1.5 py-1 text-left">For</th>
                            <th className="px-1.5 py-1 text-left">Longs</th>
                            <th className="px-1.5 py-1 text-right">Rank IC</th>
                            <th className="px-1.5 py-1 text-right">L/S spread</th>
                            <th className="px-1.5 py-1 text-right"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {vSignals.map((s: SeasonalSignal) => (
                            <tr key={s.id} className="border-b border-line/40 last:border-0">
                              <td className="px-1.5 py-1 text-left text-fg-muted">{s.signal_ref}</td>
                              <td className="px-1.5 py-1 text-left">{s.for_month}</td>
                              <td className="px-1.5 py-1 text-left text-fg-muted">
                                {s.long_candidates.slice(0, 3).map((c: MonthRankingRow) => short(c.sector)).join(", ") || "—"}
                              </td>
                              <td className="px-1.5 py-1 text-right">
                                {s.review?.rank_ic == null ? "—" : num(s.review.rank_ic, 3)}
                              </td>
                              <td
                                className={cn(
                                  "px-1.5 py-1 text-right",
                                  (s.review?.long_short_spread_pct ?? 0) < 0 ? "text-neg" : "text-pos",
                                )}
                              >
                                {s.review?.long_short_spread_pct == null
                                  ? "—"
                                  : `${num(s.review.long_short_spread_pct, 2)}%`}
                              </td>
                              <td className="px-1.5 py-1 text-right">
                                {s.status === "generated" && (
                                  <button
                                    className="text-accent hover:underline"
                                    onClick={() => review.mutate(s.id)}
                                  >
                                    review
                                  </button>
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
            })}
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={cn("inline-block h-3 w-3 rounded-sm border border-line", cls)} />
      {label}
    </span>
  );
}

function CandidateList({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: MonthRankingRow[];
  tone: "pos" | "neg";
}) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">{title}</p>
      {rows.length === 0 ? (
        <p className="mt-1 text-xs text-fg-faint">Nothing clears the score filter.</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {rows.map((r) => (
            <li key={r.sector} className="flex items-center justify-between text-xs">
              <span className="text-fg-muted">{short(r.sector)}</span>
              <span className="tabular-nums">
                <span className={tone === "pos" ? "text-pos" : "text-neg"}>
                  {r.mean_edge_pct >= 0 ? "+" : ""}
                  {num(r.mean_edge_pct, 1)}%
                </span>
                <span className="ml-2 text-fg-faint">
                  {tone === "pos" ? "L" : "S"}
                  {num(tone === "pos" ? r.long_score : r.short_score, 0)} · t{num(r.t_stat, 1)} · n
                  {r.n}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MonthGrids({ report }: { report: import("@/api/seasonality").SeasonalityReport }) {
  const months = report.months ?? {};
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {[
        { key: "long", label: "Best sectors, month by month", pick: "long_candidates" as const },
        { key: "short", label: "Worst sectors, month by month", pick: "short_candidates" as const },
      ].map((col) => (
        <SectionCard key={col.key} title={col.label} index={col.key === "long" ? 3 : 4}>
          <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2">
            {MONTHS.map((mn, i) => {
              const blk = months[String(i + 1)];
              const rows = blk?.[col.pick] ?? [];
              return (
                <div key={mn} className="rounded-md border border-line/70 bg-bg/40 p-2">
                  <p className="text-xs font-semibold text-fg">{mn}</p>
                  {rows.length === 0 ? (
                    <p className="mt-0.5 text-[10px] text-fg-faint">—</p>
                  ) : (
                    <ul className="mt-0.5 space-y-0.5">
                      {rows.slice(0, 3).map((r) => (
                        <li
                          key={r.sector}
                          className="flex items-center justify-between text-[11px]"
                        >
                          <span className="text-fg-muted">{short(r.sector)}</span>
                          <span
                            className={cn(
                              "tabular-nums",
                              r.mean_edge_pct >= 0 ? "text-pos" : "text-neg",
                            )}
                          >
                            {r.mean_edge_pct >= 0 ? "+" : ""}
                            {num(r.mean_edge_pct, 1)}% · t{num(r.t_stat, 1)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </SectionCard>
      ))}
    </div>
  );
}

function CellDetail({ cell }: { cell: SeasonCell }) {
  const hz = cell.horizons?.by_horizon ?? {};
  const rg = cell.regime;
  return (
    <div className="grid grid-cols-1 gap-4 p-3 text-[11px] md:grid-cols-3">
      <div>
        <p className="font-semibold uppercase tracking-wide text-fg-faint">
          {short(cell.sector)} · {MONTHS[cell.month - 1]} · n={cell.n}
        </p>
        <dl className="mt-1 space-y-0.5">
          <Row k="Mean edge" v={`${num(cell.mean_edge_pct, 2)}%`} />
          <Row k="Median edge" v={`${num(cell.median_edge_pct, 2)}%`} />
          <Row k="Raw month return" v={`${num(cell.mean_return_pct, 2)}%`} />
          <Row k="Win / loss" v={`${Math.round(cell.win_rate * 100)}% / ${Math.round(cell.loss_rate * 100)}%`} />
          <Row k="Worst year" v={`${num(cell.min_edge_pct, 2)}%`} />
          <Row k="Std of edge" v={`${num(cell.std_edge_pct, 2)}%`} />
        </dl>
      </div>
      <div>
        <p className="font-semibold uppercase tracking-wide text-fg-faint">Significance</p>
        <dl className="mt-1 space-y-0.5">
          <Row k="t-stat" v={num(cell.t_stat, 2)} />
          <Row k="p-value" v={num(cell.p_value, 3)} />
          <Row k="FDR q-value" v={num(cell.q_value ?? null, 3)} />
          <Row k="Verdict" v={cell.fdr_label ?? cell.t_label} />
          <Row k="Effect size d" v={num(cell.effect_size_d, 2)} />
          {cell.bootstrap?.available && (
            <>
              <Row
                k="Bootstrap 95% CI"
                v={`${num(cell.bootstrap.ci95?.[0] ?? null, 1)} … ${num(cell.bootstrap.ci95?.[1] ?? null, 1)}`}
              />
              <Row k="P(edge > 0)" v={num(cell.bootstrap.prob_positive ?? null, 2)} />
            </>
          )}
          <Row k="Confidence" v={`${num(cell.confidence ?? null, 0)} / 100`} />
        </dl>
      </div>
      <div>
        <p className="font-semibold uppercase tracking-wide text-fg-faint">
          Stability · {cell.horizons?.stability ?? "—"}
        </p>
        <dl className="mt-1 space-y-0.5">
          {["max", "20y", "15y", "10y", "5y", "3y"].map((h) => (
            <Row
              key={h}
              k={h}
              v={
                hz[h]?.mean_edge_pct == null
                  ? `n=${hz[h]?.n ?? 0}`
                  : `${num(hz[h].mean_edge_pct, 2)}%  (n=${hz[h].n})`
              }
            />
          ))}
        </dl>
        {rg && (
          <>
            <p className="mt-2 font-semibold uppercase tracking-wide text-fg-faint">By regime</p>
            <dl className="mt-1 space-y-0.5">
              <Row k="Bull tape" v={rg.bull.mean_edge_pct == null ? "—" : `${num(rg.bull.mean_edge_pct, 2)}%`} />
              <Row k="Bear tape" v={rg.bear.mean_edge_pct == null ? "—" : `${num(rg.bear.mean_edge_pct, 2)}%`} />
              <Row k="High vol" v={rg.high_vol.mean_edge_pct == null ? "—" : `${num(rg.high_vol.mean_edge_pct, 2)}%`} />
              {rg.regime_dependent && (
                <p className="text-amber-500">Edge flips materially with the regime.</p>
              )}
            </dl>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-fg-faint">{k}</dt>
      <dd className="tabular-nums text-fg-muted">{v}</dd>
    </div>
  );
}

function BacktestPanel() {
  const [strategy, setStrategy] = useState("E_long_top3_short_bottom3");
  const [mode, setMode] = useState("expanding");
  const [longBps, setLongBps] = useState(30);
  const [shortBps, setShortBps] = useState(60);
  const { data: bt, isLoading } = useSeasonalityBacktest({
    strategy,
    mode,
    start_test_year: 2012,
    long_cost_bps: longBps,
    short_cost_bps: shortBps,
  });

  return (
    <SectionCard
      title="Walk-forward backtest (strictly out-of-sample)"
      index={9}
      actions={
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            className="h-7 rounded border border-line bg-surface px-1.5"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            {Object.entries(STRATEGY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            className="h-7 rounded border border-line bg-surface px-1.5"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="expanding">expanding window</option>
            <option value="rolling">rolling 12y</option>
          </select>
          <label className="flex items-center gap-1 text-fg-faint">
            L bps
            <input
              type="number"
              className="h-7 w-14 rounded border border-line bg-surface px-1 tabular-nums"
              value={longBps}
              onChange={(e) => setLongBps(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1 text-fg-faint">
            S bps
            <input
              type="number"
              className="h-7 w-14 rounded border border-line bg-surface px-1 tabular-nums"
              value={shortBps}
              onChange={(e) => setShortBps(Number(e.target.value))}
            />
          </label>
        </div>
      }
    >
      <div className="p-4">
        {isLoading || !bt ? (
          <p className="py-6 text-center text-sm text-fg-faint">Running walk-forward…</p>
        ) : (
          <BacktestBody bt={bt} />
        )}
      </div>
    </SectionCard>
  );
}

function BacktestBody({ bt }: { bt: WalkForwardResult }) {
  const curve = bt.equity_curve.map(([d, v]) => ({ d, v: Number((v * 100 - 100).toFixed(2)) }));
  const m = bt.metrics;
  const oo = bt.oos_split.out_of_sample;
  const is = bt.oos_split.in_sample;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-fg-faint">
        {bt.start_test} → {bt.end_test} · {bt.n_months} test months · each month re-ranks sectors
        from earlier data only · costs {bt.long_cost_bps}bps long / {bt.short_cost_bps}bps short.
      </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="CAGR" value={`${num(m.cagr_pct, 1)}%`} tone={(m.cagr_pct ?? 0) >= 0} />
        <Stat label="Sharpe" value={num(m.sharpe, 2)} />
        <Stat label="Max DD" value={`${num(m.max_dd_pct, 1)}%`} tone={false} />
        <Stat label="Monthly win" value={`${num(m.monthly_win_rate_pct, 0)}%`} />
        <Stat
          label="Rank IC (mean)"
          value={num(bt.rank_ic.mean, 3)}
          tone={(bt.rank_ic.mean ?? 0) > 0.05}
        />
        <Stat label="IC+ months" value={`${num(bt.rank_ic.pct_positive_months, 0)}%`} />
        <Stat
          label="Long-short spread"
          value={bt.spread.mean_pct == null ? "–" : `${num(bt.spread.mean_pct, 2)}%/mo`}
          tone={(bt.spread.mean_pct ?? 0) > 0}
        />
        <Stat label="Spread+ months" value={`${num(bt.spread.pct_positive_months, 0)}%`} />
      </div>

      <div className="rounded-md border border-line/70 bg-bg/40 p-2.5">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
          In-sample vs out-of-sample
        </p>
        <div className="mt-1 grid grid-cols-2 gap-2 text-xs tabular-nums">
          {[
            ["In-sample", is],
            ["Out-of-sample", oo],
          ].map(([lbl, seg]) => (
            <div key={lbl as string} className="rounded bg-surface p-1.5">
              <p className="text-[9px] uppercase tracking-wide text-fg-faint">{lbl as string}</p>
              <p
                className={cn(
                  "font-semibold",
                  Number((seg as Record<string, number>).cagr_pct) < 0 ? "text-neg" : "text-pos",
                )}
              >
                CAGR {num((seg as Record<string, number>).cagr_pct, 1)}%
              </p>
              <p className="text-[10px] text-fg-faint">
                Sharpe {num((seg as Record<string, number>).sharpe, 2)} · win{" "}
                {num((seg as Record<string, number>).monthly_win_rate_pct, 0)}%
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="h-56 w-full">
        <ResponsiveContainer>
          <AreaChart data={curve} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" />
            <XAxis
              dataKey="d"
              stroke="var(--color-fg-faint)"
              fontSize={11}
              minTickGap={40}
              tickFormatter={(d: string) => d}
            />
            <YAxis
              stroke="var(--color-fg-faint)"
              fontSize={11}
              width={48}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-line)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={((v: unknown) => [`${num(Number(v), 2)}%`, "Cumulative"]) as never}
            />
            <Area
              type="monotone"
              dataKey="v"
              stroke="var(--color-accent)"
              fill="var(--color-accent)"
              fillOpacity={0.12}
              strokeWidth={1.75}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-fg-faint">
        The long-only variants (A, C) can look profitable, but that is market beta — every
        sector index rose over this window. The long/short variants (E, F) isolate the seasonal
        signal, and a rank IC near zero with a small, cost-sensitive spread is the real
        read-out.
      </p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "tabular-nums text-sm font-semibold",
          tone == null ? "text-fg" : tone ? "text-pos" : "text-neg",
        )}
      >
        {value}
      </span>
    </div>
  );
}
