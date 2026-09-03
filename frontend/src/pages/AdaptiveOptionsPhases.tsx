/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMemo, useState } from "react";

import type { Json } from "@/api/adaptiveOptions";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Sparkline } from "@/components/Sparkline";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useAdaptiveBacktest,
  useAdaptiveConfig,
  useAdaptiveDecision,
  useAdaptiveExpiries,
  useAdaptiveStrategyMatrix,
  useAdaptiveValidation,
  usePaperRun,
  usePaperRunAction,
  usePaperRuns,
  useStartPaperRun,
} from "@/hooks/useAdaptiveOptions";
import { cn } from "@/lib/utils";

const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] as const;
const PRESETS = ["conservative", "balanced", "aggressive"] as const;
const selCls = "h-9 rounded-md border border-line-strong bg-surface px-2.5 text-sm text-fg";

const n = (v: any, d = 2) =>
  v == null || Number.isNaN(Number(v))
    ? "–"
    : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d });
const inr = (v: any) => (v == null ? "–" : `₹${n(v, 0)}`);
const pct = (v: any, d = 1) => (v == null ? "–" : `${Number(v).toFixed(d)}%`);

function Bar({ v, tone }: { v: number; tone?: string }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-elevated">
      <div
        className={cn("h-full rounded-full", tone ?? "bg-accent")}
        style={{ width: `${Math.max(0, Math.min(100, v))}%` }}
      />
    </div>
  );
}

function KpiRow({ items }: { items: [string, string, ("pos" | "neg" | "muted")?][] }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, value, tone]) => (
        <StatCard key={label} label={label} value={value} valueClassName="text-base" deltaTone={tone} />
      ))}
    </div>
  );
}

function ContextControls({
  underlying,
  setUnderlying,
  expiry,
  setExpiry,
  preset,
  setPreset,
  extra,
}: {
  underlying: string;
  setUnderlying: (v: string) => void;
  expiry: string;
  setExpiry: (v: string) => void;
  preset: string;
  setPreset: (v: string) => void;
  extra?: React.ReactNode;
}) {
  const { data: exp } = useAdaptiveExpiries(underlying);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={selCls} value={underlying} onChange={(e) => setUnderlying(e.target.value)}>
        {UNDERLYINGS.map((u) => (
          <option key={u}>{u}</option>
        ))}
      </select>
      <select className={selCls} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
        <option value="">Nearest expiry</option>
        {(exp?.expiries ?? []).map((e) => (
          <option key={e}>{e}</option>
        ))}
      </select>
      <select className={selCls} value={preset} onChange={(e) => setPreset(e.target.value)}>
        {PRESETS.map((p) => (
          <option key={p} value={p}>
            {p[0].toUpperCase() + p.slice(1)}
          </option>
        ))}
      </select>
      {extra}
    </div>
  );
}

function Unavailable({ d }: { d: any }) {
  if (!d || d.available !== false) return null;
  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardContent className="py-3 text-sm">
        <span className="font-medium">Unavailable.</span> {d.reason}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------
// Strategy Engine
// --------------------------------------------------------------------------

function PositionSummary({ pos }: { pos: any }) {
  if (!pos) return null;
  const g = pos.greeks ?? {};
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-xs md:grid-cols-4">
      <span>Net premium: <b className={pos.net_premium >= 0 ? "text-pos" : "text-neg"}>{inr(pos.net_premium)}</b></span>
      <span>Max profit: <b className="text-pos">{inr(pos.max_profit)}</b></span>
      <span>Max loss: <b className="text-neg">{pos.undefined_risk ? "undefined" : inr(pos.max_loss)}</b></span>
      <span>R:R: <b>{pos.risk_reward == null ? "n/a" : n(pos.risk_reward)}</b></span>
      <span>POP: <b>{pct((pos.pop ?? 0) * 100)}</b></span>
      <span>Margin: <b>{inr(pos.margin_estimate)}</b></span>
      <span>Breakevens: <b>{(pos.breakevens ?? []).map((x: number) => n(x, 0)).join(" / ") || "–"}</b></span>
      <span>Δ {n(g.delta, 3)} · Θ {n(g.theta, 0)} · V {n(g.vega, 0)}</span>
    </div>
  );
}

function LegTable({ legs }: { legs: any[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
        <thead className="text-[10px] uppercase text-fg-faint">
          <tr>
            <th className="py-1 text-left">Side</th>
            <th className="py-1 text-left">Right</th>
            <th className="py-1 text-right">Strike</th>
            <th className="py-1 text-right">Lots</th>
            <th className="py-1 text-right">Entry</th>
            <th className="py-1 text-right">Δ</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((lg, i) => (
            <tr key={i} className="border-t border-line/60">
              <td className={cn("py-1", lg.side === "SELL" ? "text-neg" : "text-pos")}>{lg.side}</td>
              <td className="py-1">{lg.right}</td>
              <td className="py-1 text-right">{n(lg.strike, 0)}</td>
              <td className="py-1 text-right">{lg.lots}</td>
              <td className="py-1 text-right">{n(lg.entry_price)}</td>
              <td className="py-1 text-right text-fg-muted">{n(lg.delta, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdaptiveStrategyEnginePage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [preset, setPreset] = useState("balanced");
  const q = useAdaptiveDecision({ underlying, expiry: expiry || undefined, preset });
  const d = q.data as any;
  const dec = d?.decision;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Strategy Engine"
        subtitle="Ranked strategy recommendations for the current market: regime + PCR + positioning + volatility + expected move → a configurable suitability score, then the top pick sized and risk-checked."
        actions={
          <ContextControls
            {...{ underlying, setUnderlying, expiry, setExpiry, preset, setPreset }}
            extra={
              <Button variant="secondary" size="sm" onClick={() => q.refetch()} disabled={q.isFetching}>
                {q.isFetching ? "Analysing…" : "Refresh"}
              </Button>
            }
          />
        }
      />
      {q.isLoading && <p className="text-sm text-fg-faint">Running the pipeline…</p>}
      <Unavailable d={d} />
      {d?.available && dec && (
        <>
          <KpiRow
            items={[
              ["Regime", d.regime.label.replace(/_/g, " "), d.regime.direction === "BULLISH" ? "pos" : d.regime.direction === "BEARISH" ? "neg" : "muted"],
              ["Decision", dec.action, dec.action === "ENTER" ? "pos" : dec.action === "NO_TRADE" ? "neg" : "muted"],
              ["Confidence", n(d.confidence.score, 0), d.confidence.score >= 70 ? "pos" : d.confidence.score < 40 ? "neg" : "muted"],
              ["Weighted PCR", n(d.pcr.weighted_pcr), "muted"],
              ["IV class", d.volatility.iv_class.replace(/_/g, " "), "muted"],
              ["Expected move", d.expected_move.points ? `±${n(d.expected_move.points, 0)}` : "–", "muted"],
            ]}
          />

          {dec.action !== "ENTER" && (
            <Card className="border-amber-500/40 bg-amber-500/5">
              <CardContent className="py-3 text-sm">
                <Badge variant="warning">{dec.action}</Badge>{" "}
                {dec.no_trade_reason || "No strategy cleared the suitability floor for this market."}
              </CardContent>
            </Card>
          )}

          {dec.expiry_guidance?.length > 0 && (
            <Card className="border-sky-500/30 bg-sky-500/5">
              <CardContent className="py-2.5 text-xs text-fg-muted">
                {dec.expiry_guidance.map((g: string, i: number) => (
                  <div key={i}>· {g}</div>
                ))}
              </CardContent>
            </Card>
          )}

          {dec.entry && (
            <SectionCard title="Top pick — sized & risk-checked">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">{dec.top.name}</span>
                <Badge variant={dec.entry.actionable ? "success" : "warning"}>
                  {dec.entry.actionable ? `${dec.entry.final_lots} lots` : "not actionable"}
                </Badge>
                <span className="text-xs text-fg-faint">
                  capital at risk {inr(dec.entry.sized.capital_at_risk)} · margin {inr(dec.entry.sized.margin)}
                </span>
              </div>
              {!dec.entry.risk.ok && (
                <p className="mb-2 text-xs text-neg">Risk engine: {dec.entry.risk.blocked_reason}</p>
              )}
              {dec.entry.risk.warnings?.map((w: string, i: number) => (
                <p key={i} className="text-[11px] text-fg-faint">· {w}</p>
              ))}
              <LegTable legs={dec.top.position.legs} />
              <div className="mt-2">
                <PositionSummary pos={dec.top.position} />
              </div>
            </SectionCard>
          )}

          <SectionCard title={`Ranked strategies (${dec.ranked.length})`}>
            <div className="flex flex-col gap-2.5">
              {dec.ranked.map((r: any) => (
                <div key={r.slug} className="rounded-md border border-line p-3">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{r.name}</span>
                    <div className="flex items-center gap-2">
                      <Badge variant={r.risk_level === "UNDEFINED" ? "destructive" : r.risk_level === "HIGH" ? "warning" : "default"}>
                        {r.risk_level}
                      </Badge>
                      <span className="w-10 text-right text-sm font-semibold tabular-nums">
                        {n(r.suitability, 0)}
                      </span>
                    </div>
                  </div>
                  <Bar v={r.suitability} tone={r.suitability >= 65 ? "bg-pos" : r.suitability >= 45 ? "bg-accent" : "bg-neg"} />
                  <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-fg-muted md:grid-cols-4">
                    {Object.entries(r.components).map(([k, v]: any) => (
                      <span key={k}>{k.replace(/_/g, " ")}: {n(v, 0)}</span>
                    ))}
                  </div>
                  <PositionSummary pos={r.position} />
                </div>
              ))}
              {dec.ranked.length === 0 && <p className="text-xs text-fg-faint">No strategies cleared the floor.</p>}
            </div>
          </SectionCard>

          {dec.avoid?.length > 0 && (
            <SectionCard title={`Avoid (${dec.avoid.length})`}>
              <div className="flex flex-wrap gap-1.5 text-[11px]">
                {dec.avoid.map((a: any) => (
                  <span key={a.slug} className="rounded border border-line px-2 py-0.5 text-fg-muted">
                    {a.slug}: {a.reason}
                  </span>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Strategy Builder — strike selection detail
// --------------------------------------------------------------------------

export function AdaptiveStrategyBuilderPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [preset, setPreset] = useState("balanced");
  const [method, setMethod] = useState("");
  const overrides = method ? { strike_method: method } : null;
  const q = useAdaptiveDecision({ underlying, expiry: expiry || undefined, preset, overrides });
  const d = q.data as any;
  const top = d?.decision?.top;
  const strikes = top?.strikes;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Strategy Builder"
        subtitle="How the engine chose the strikes for the top-ranked structure, and the resulting legs. Override the strike-selection method to see alternatives."
        actions={
          <ContextControls
            {...{ underlying, setUnderlying, expiry, setExpiry, preset, setPreset }}
            extra={
              <select className={selCls} value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="">Method: preset default</option>
                {["delta", "expected_move", "oi_wall", "support_resistance", "premium"].map((m) => (
                  <option key={m} value={m}>{m.replace(/_/g, " ")}</option>
                ))}
              </select>
            }
          />
        }
      />
      <Unavailable d={d} />
      {d?.available && !top && (
        <Card><CardContent className="py-3 text-sm text-fg-muted">
          The engine is not recommending an entry right now ({d.decision?.action}) — no strike plan to show.
        </CardContent></Card>
      )}
      {d?.available && top && strikes && (
        <>
          <SectionCard title={`${top.name} · strike plan (${strikes.method})`}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-[10px] uppercase text-fg-faint">
                  <tr>
                    <th className="py-1 text-left">Level</th>
                    <th className="py-1 text-right">Strike</th>
                    <th className="py-1 text-right">|Δ|</th>
                    <th className="py-1 text-right">Call OI</th>
                    <th className="py-1 text-right">Put OI</th>
                    <th className="py-1 text-left">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(strikes.levels).map(([name, k]: any) => (
                    <tr key={name} className="border-t border-line/60">
                      <td className="py-1 font-medium">{name}</td>
                      <td className="py-1 text-right">{n(k, 0)}</td>
                      <td className="py-1 text-right text-fg-muted">{n(strikes.per_leg?.[name]?.delta, 3)}</td>
                      <td className="py-1 text-right text-fg-muted">{n(strikes.per_leg?.[name]?.call_oi, 0)}</td>
                      <td className="py-1 text-right text-fg-muted">{n(strikes.per_leg?.[name]?.put_oi, 0)}</td>
                      <td className="py-1 text-left text-fg-muted">{strikes.reasons?.[name]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {strikes.notes?.map((nn: string, i: number) => (
              <p key={i} className="mt-1 text-[11px] text-fg-faint">{nn}</p>
            ))}
          </SectionCard>
          <SectionCard title="Resulting legs">
            <LegTable legs={top.position.legs} />
            <div className="mt-2"><PositionSummary pos={top.position} /></div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Strategy Comparison
// --------------------------------------------------------------------------

export function AdaptiveComparisonPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [preset, setPreset] = useState("balanced");
  const { data: matrix } = useAdaptiveStrategyMatrix(preset);
  const all: any[] = matrix?.decision_matrix ?? [];
  const [picked, setPicked] = useState<string[]>([]);
  const slugs = picked.length ? picked : all.slice(0, 4).map((x) => x.slug);
  const q = useAdaptiveDecision({ underlying, expiry: expiry || undefined, preset, compareSlugs: slugs });
  const rows: any[] = (q.data as any)?.decision?.comparison ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Strategy Comparison"
        subtitle="Score a chosen set of strategies against the current market side by side — so it's clear why one is picked over another."
        actions={<ContextControls {...{ underlying, setUnderlying, expiry, setExpiry, preset, setPreset }} />}
      />
      <SectionCard title="Choose strategies">
        <div className="flex flex-wrap gap-1.5">
          {all.map((s) => {
            const on = slugs.includes(s.slug);
            return (
              <button
                key={s.slug}
                onClick={() =>
                  setPicked((p) =>
                    p.includes(s.slug) ? p.filter((x) => x !== s.slug) : [...p, s.slug],
                  )
                }
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px]",
                  on ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted",
                )}
              >
                {s.strategy}
              </button>
            );
          })}
        </div>
      </SectionCard>
      <Unavailable d={q.data} />
      {rows.length > 0 && (
        <SectionCard title="Comparison" bodyClassName="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="bg-surface-2 text-[10px] uppercase text-fg-faint">
                <tr>
                  {["Strategy", "Suitability", "Risk", "POP", "Max profit", "Max loss", "R:R", "Margin", "Δ", "Θ", "V"].map((h) => (
                    <th key={h} className="px-2 py-1.5 text-right first:text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r: any) => {
                  const p = r.position ?? {};
                  const g = p.greeks ?? {};
                  return (
                    <tr key={r.slug} className="border-t border-line/60">
                      <td className="px-2 py-1.5 text-left font-medium">{r.name ?? r.slug}</td>
                      <td className="px-2 py-1.5 text-right">
                        {r.avoided ? <span className="text-neg">avoid</span> : n(r.suitability, 0)}
                      </td>
                      <td className="px-2 py-1.5 text-right text-fg-muted">{r.risk_level ?? "–"}</td>
                      <td className="px-2 py-1.5 text-right">{p.pop == null ? "–" : pct(p.pop * 100)}</td>
                      <td className="px-2 py-1.5 text-right text-pos">{inr(p.max_profit)}</td>
                      <td className="px-2 py-1.5 text-right text-neg">{p.undefined_risk ? "undef" : inr(p.max_loss)}</td>
                      <td className="px-2 py-1.5 text-right">{p.risk_reward == null ? "–" : n(p.risk_reward)}</td>
                      <td className="px-2 py-1.5 text-right">{inr(p.margin_estimate)}</td>
                      <td className="px-2 py-1.5 text-right text-fg-muted">{n(g.delta, 2)}</td>
                      <td className="px-2 py-1.5 text-right text-fg-muted">{n(g.theta, 0)}</td>
                      <td className="px-2 py-1.5 text-right text-fg-muted">{n(g.vega, 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Backtesting
// --------------------------------------------------------------------------

export function AdaptiveBacktestingPage() {
  const { data: cfg } = useAdaptiveConfig();
  const [advanced, setAdvanced] = useState(false);
  const [form, setForm] = useState({
    underlying: "NIFTY",
    risk_level: "moderate",
    preset: "balanced",
    capital: 1_000_000,
    start: "2025-10-01",
    end: "2026-02-01",
    expiry_kind: "weekly",
    data_source: "synthetic",
    overrides: "{}",
  });
  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const run = useAdaptiveBacktest();
  const res = run.data as any;

  function submit() {
    let overrides: Json | null = null;
    if (advanced && form.overrides.trim() && form.overrides.trim() !== "{}") {
      try {
        overrides = JSON.parse(form.overrides);
      } catch {
        alert("Overrides is not valid JSON");
        return;
      }
    }
    run.mutate({
      underlying: form.underlying,
      start: form.start,
      end: form.end,
      mode: advanced ? "advanced" : "simple",
      preset: advanced ? form.preset : "balanced",
      risk_level: form.risk_level,
      capital: form.capital,
      overrides,
      expiry_kind: form.expiry_kind,
      data_source: form.data_source,
    });
  }

  const eq = (res?.equity_curve ?? []).map((r: any[]) => r[1]);
  const m = res?.metrics ?? {};

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Backtesting"
        subtitle="Walk-forward: the same decision engine makes one call per trading day, then manages the structure. Synthetic chain by default (mechanics only, flagged); bhavcopy uses real NSE EOD open interest where the archive download works."
        actions={
          <Button variant="ghost" size="sm" onClick={() => setAdvanced((s) => !s)}>
            {advanced ? "Simple mode" : "Advanced mode"}
          </Button>
        }
      />
      <SectionCard title={advanced ? "Advanced configuration" : "Simple backtest"}>
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-4">
          <div className="flex flex-col gap-1"><Label>Instrument</Label>
            <select className={selCls} value={form.underlying} onChange={(e) => set("underlying", e.target.value)}>
              {UNDERLYINGS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
          {!advanced ? (
            <div className="flex flex-col gap-1"><Label>Risk level</Label>
              <select className={selCls} value={form.risk_level} onChange={(e) => set("risk_level", e.target.value)}>
                {["conservative", "moderate", "aggressive"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
          ) : (
            <div className="flex flex-col gap-1"><Label>Preset</Label>
              <select className={selCls} value={form.preset} onChange={(e) => set("preset", e.target.value)}>
                {PRESETS.map((p) => <option key={p}>{p}</option>)}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-1"><Label>Capital (₹)</Label>
            <Input type="number" value={form.capital} onChange={(e) => set("capital", Number(e.target.value))} />
          </div>
          <div className="flex flex-col gap-1"><Label>Expiry</Label>
            <select className={selCls} value={form.expiry_kind} onChange={(e) => set("expiry_kind", e.target.value)}>
              <option value="weekly">Weekly</option><option value="monthly">Monthly</option>
            </select>
          </div>
          <div className="flex flex-col gap-1"><Label>Start</Label>
            <Input type="date" value={form.start} onChange={(e) => set("start", e.target.value)} />
          </div>
          <div className="flex flex-col gap-1"><Label>End</Label>
            <Input type="date" value={form.end} onChange={(e) => set("end", e.target.value)} />
          </div>
          <div className="flex flex-col gap-1"><Label>Data source</Label>
            <select className={selCls} value={form.data_source} onChange={(e) => set("data_source", e.target.value)}>
              <option value="synthetic">Synthetic (mechanics)</option>
              <option value="auto">Auto (bhavcopy → synthetic)</option>
              <option value="bhavcopy">Bhavcopy only (NSE EOD OI)</option>
              <option value="local">Local history (Kaggle / GitHub CSV)</option>
              <option value="local_bhavcopy">Local history → bhavcopy → synthetic</option>
            </select>
          </div>
        </div>
        {advanced && (
          <div className="mt-3 flex flex-col gap-1">
            <Label>Config overrides (JSON — any AdaptiveConfig field)</Label>
            <textarea
              className="h-24 rounded-md border border-line-strong bg-surface p-2 font-mono text-xs text-fg"
              value={form.overrides}
              onChange={(e) => set("overrides", e.target.value)}
            />
            <p className="text-[11px] text-fg-faint">
              {cfg?.fields?.slice(0, 12).join(", ")}… ({cfg?.fields?.length ?? 0} fields)
            </p>
          </div>
        )}
        <div className="mt-3">
          <Button onClick={submit} disabled={run.isPending}>
            {run.isPending ? "Running…" : "Run backtest"}
          </Button>
        </div>
        {run.isError && <p className="mt-2 text-xs text-neg">{(run.error as Error).message}</p>}
      </SectionCard>

      {res?.available && (
        <>
          {res.synthetic_data && (
            <Card className="border-amber-500/40 bg-amber-500/5">
              <CardContent className="py-2.5 text-xs">
                {res.warnings?.map((w: string, i: number) => <div key={i}>· {w}</div>)}
              </CardContent>
            </Card>
          )}
          <KpiRow
            items={[
              ["Total return", pct(m.total_return_pct), (m.total_return_pct ?? 0) >= 0 ? "pos" : "neg"],
              ["Net P&L", inr(m.net_pnl), (m.net_pnl ?? 0) >= 0 ? "pos" : "neg"],
              ["Max drawdown", pct(m.max_drawdown_pct), "neg"],
              ["Sharpe", n(m.sharpe_ratio), (m.sharpe_ratio ?? 0) >= 1 ? "pos" : "muted"],
              ["Win rate", pct(m.win_rate_pct), "muted"],
              ["Trades", n(m.total_trades, 0), "muted"],
            ]}
          />
          <SectionCard title="Equity curve">
            {eq.length > 1 ? (
              <div className="h-24">
                <Sparkline data={eq} tone={eq[eq.length - 1] >= eq[0] ? "accent" : "neg"} />
              </div>
            ) : (
              <p className="text-xs text-fg-faint">Not enough points.</p>
            )}
            <p className="mt-1 text-[11px] text-fg-faint">
              PF {n(m.profit_factor)} · Sortino {n(m.sortino_ratio)} · Calmar {n(m.calmar_ratio)} ·
              expectancy {inr(m.expectancy)} · avg hold {n(m.avg_holding_days, 1)}d · VaR5 {inr(m.value_at_risk_5pct)} ·
              CVaR5 {inr(m.conditional_var_5pct)} · exposure {pct(m.exposure_pct)}
            </p>
          </SectionCard>

          <div className="grid gap-4 md:grid-cols-2">
            <AttrTable title="By strategy" data={res.attribution?.by_strategy} />
            <AttrTable title="By regime at entry" data={res.attribution?.by_regime_at_entry} />
            <AttrTable title="By weekday" data={res.attribution?.by_weekday} />
            <AttrTable title="By DTE bucket" data={res.attribution?.by_dte_bucket} />
          </div>

          <SectionCard title={`Trades (${res.trades.length})`} bodyClassName="p-0">
            <div className="max-h-96 overflow-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="sticky top-0 bg-surface-2 text-[10px] uppercase text-fg-faint">
                  <tr>
                    {["Entry", "Exit", "Strategy", "Regime", "Lots", "Net P&L", "Costs", "Adj", "Reason"].map((h) => (
                      <th key={h} className="px-2 py-1.5 text-right first:text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {res.trades.map((t: any, i: number) => (
                    <tr key={i} className="border-t border-line/50">
                      <td className="px-2 py-1 text-left">{t.entry_date}</td>
                      <td className="px-2 py-1 text-left">{t.exit_date}</td>
                      <td className="px-2 py-1 text-left">{t.strategy}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{t.regime_at_entry}</td>
                      <td className="px-2 py-1 text-right">{t.lots}</td>
                      <td className={cn("px-2 py-1 text-right", t.net_pnl >= 0 ? "text-pos" : "text-neg")}>{inr(t.net_pnl)}</td>
                      <td className="px-2 py-1 text-right text-fg-muted">{inr(t.costs)}</td>
                      <td className="px-2 py-1 text-right">{t.adjustments}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <DecisionLogTable rows={res.decision_log} total={res.decision_log_len} />
        </>
      )}
    </div>
  );
}

function AttrTable({ title, data }: { title: string; data: any }) {
  const rows = Object.entries(data ?? {});
  return (
    <SectionCard title={title}>
      {rows.length === 0 ? (
        <p className="text-xs text-fg-faint">No trades.</p>
      ) : (
        <table className="w-full text-xs tabular-nums">
          <tbody>
            {rows.map(([k, v]: any) => (
              <tr key={k} className="border-b border-line/60 last:border-0">
                <td className="py-1 text-left">{k}</td>
                <td className="py-1 text-right text-fg-muted">{v.trades} trades</td>
                <td className={cn("py-1 text-right", v.net_pnl >= 0 ? "text-pos" : "text-neg")}>{inr(v.net_pnl)}</td>
                <td className="py-1 text-right text-fg-muted">{pct(v.win_rate_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </SectionCard>
  );
}

function DecisionLogTable({ rows, total }: { rows: any[]; total?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <SectionCard
      title={`Decision log${total ? ` (${total})` : ""}`}
      actions={
        <Button variant="ghost" size="sm" onClick={() => setOpen((s) => !s)}>
          {open ? "Hide" : `Show last ${Math.min(rows?.length ?? 0, 500)}`}
        </Button>
      }
      bodyClassName={open ? "p-0" : undefined}
    >
      {!open ? (
        <p className="text-xs text-fg-faint">
          Every session's regime, action and reason — expand to inspect.
        </p>
      ) : (
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-surface-2 text-[10px] uppercase text-fg-faint">
              <tr>
                {["Date", "Phase", "Regime", "Action", "Strategy", "Reason", "Pos P&L"].map((h) => (
                  <th key={h} className="px-2 py-1.5 text-right first:text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r: any, i: number) => (
                <tr key={i} className="border-t border-line/50">
                  <td className="px-2 py-1 text-left">{(r.date ?? r.ts ?? "").slice(0, 10)}</td>
                  <td className="px-2 py-1 text-left text-fg-muted">{r.phase}</td>
                  <td className="px-2 py-1 text-left">{r.regime}</td>
                  <td className="px-2 py-1 text-left">
                    <Badge variant={r.action === "ENTER" ? "success" : r.action === "NO_TRADE" ? "warning" : "default"}>
                      {r.action}
                    </Badge>
                  </td>
                  <td className="px-2 py-1 text-left text-fg-muted">{r.strategy ?? "–"}</td>
                  <td className="px-2 py-1 text-left text-fg-muted">{r.reason}</td>
                  <td className={cn("px-2 py-1 text-right", (r.position_pnl ?? 0) >= 0 ? "text-pos" : "text-neg")}>
                    {r.position_pnl == null ? "–" : inr(r.position_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

// --------------------------------------------------------------------------
// Validation
// --------------------------------------------------------------------------

export function AdaptiveValidationPage() {
  const [form, setForm] = useState({
    underlying: "NIFTY",
    preset: "balanced",
    start: "2025-06-01",
    end: "2026-02-01",
    n_folds: 3,
    mc_sims: 400,
    data_source: "synthetic",
  });
  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const run = useAdaptiveValidation();
  const r = run.data as any;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Validation"
        subtitle="Walk-forward out-of-sample windows, Monte Carlo on trade P&L, and parameter-sensitivity sweeps — to check the decision process isn't fragile. Runs many backtests; be patient."
      />
      <SectionCard title="Validation run">
        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
          <div className="flex flex-col gap-1"><Label>Instrument</Label>
            <select className={selCls} value={form.underlying} onChange={(e) => set("underlying", e.target.value)}>
              {UNDERLYINGS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1"><Label>Preset</Label>
            <select className={selCls} value={form.preset} onChange={(e) => set("preset", e.target.value)}>
              {PRESETS.map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1"><Label>Start</Label>
            <Input type="date" value={form.start} onChange={(e) => set("start", e.target.value)} />
          </div>
          <div className="flex flex-col gap-1"><Label>End</Label>
            <Input type="date" value={form.end} onChange={(e) => set("end", e.target.value)} />
          </div>
          <div className="flex flex-col gap-1"><Label>Folds</Label>
            <Input type="number" min={2} max={6} value={form.n_folds} onChange={(e) => set("n_folds", Number(e.target.value))} />
          </div>
          <div className="flex flex-col gap-1"><Label>MC sims</Label>
            <Input type="number" min={50} max={2000} step={50} value={form.mc_sims} onChange={(e) => set("mc_sims", Number(e.target.value))} />
          </div>
          <div className="flex flex-col gap-1"><Label>Data source</Label>
            <select className={selCls} value={form.data_source} onChange={(e) => set("data_source", e.target.value)}>
              <option value="synthetic">Synthetic (mechanics)</option>
              <option value="auto">Auto (bhavcopy → synthetic)</option>
              <option value="bhavcopy">Bhavcopy only (NSE EOD OI)</option>
              <option value="local">Local history (Kaggle / GitHub CSV)</option>
              <option value="local_bhavcopy">Local history → bhavcopy → synthetic</option>
            </select>
          </div>
        </div>
        <div className="mt-3">
          <Button onClick={() => run.mutate({ ...form })} disabled={run.isPending}>
            {run.isPending ? "Validating…" : "Run validation"}
          </Button>
        </div>
        {run.isError && <p className="mt-2 text-xs text-neg">{(run.error as Error).message}</p>}
      </SectionCard>

      {r?.available && (
        <>
          <Card className={r.overfit_flag ? "border-red-500/40 bg-red-500/5" : "border-pos/40 bg-pos/5"}>
            <CardContent className="py-3 text-sm">
              <Badge variant={r.overfit_flag ? "destructive" : "success"}>
                {r.overfit_flag ? "FRAGILE" : "ROBUST"}
              </Badge>{" "}
              {r.verdict}
              {r.synthetic_data && (
                <span className="text-fg-faint"> · synthetic data — this checks stability, not profitability</span>
              )}
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <SectionCard title="In-sample (full window)">
              <table className="w-full text-xs tabular-nums">
                <tbody>
                  {Object.entries(r.in_sample).map(([k, v]: any) => (
                    <tr key={k} className="border-b border-line/60 last:border-0">
                      <td className="py-1 text-left text-fg-faint">{k.replace(/_/g, " ")}</td>
                      <td className="py-1 text-right font-medium">{n(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>
            <SectionCard title="Walk-forward">
              <p className="mb-2 text-xs">
                Sharpe decay (IS − mean OOS): <b className={r.walk_forward.sharpe_decay > 0.5 ? "text-neg" : "text-pos"}>
                  {n(r.walk_forward.sharpe_decay)}</b>
                {" · "}OOS positive fraction: <b>{n(r.walk_forward.oos_positive_fraction)}</b>
              </p>
              <table className="w-full text-xs tabular-nums">
                <thead className="text-[10px] uppercase text-fg-faint">
                  <tr><th className="py-1 text-left">Window</th><th className="py-1 text-right">Sharpe</th>
                    <th className="py-1 text-right">Return</th><th className="py-1 text-right">MaxDD</th>
                    <th className="py-1 text-right">Trades</th></tr>
                </thead>
                <tbody>
                  {r.walk_forward.folds.map((f: any, i: number) => (
                    <tr key={i} className="border-t border-line/60">
                      <td className="py-1 text-left">{f.window[0]} → {f.window[1]}</td>
                      <td className="py-1 text-right">{n(f.sharpe_ratio)}</td>
                      <td className="py-1 text-right">{pct(f.total_return_pct)}</td>
                      <td className="py-1 text-right text-neg">{pct(f.max_drawdown_pct)}</td>
                      <td className="py-1 text-right">{f.total_trades}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>
          </div>
          <SectionCard title="Monte Carlo (trade P&L bootstrap + reshuffle)">
            {r.monte_carlo?.available === false ? (
              <p className="text-xs text-fg-faint">{r.monte_carlo.reason}</p>
            ) : (
              <pre className="max-h-64 overflow-auto rounded bg-elevated p-2 text-[11px] text-fg-muted">
                {JSON.stringify(r.monte_carlo, null, 2)}
              </pre>
            )}
          </SectionCard>
          <SectionCard title="Parameter sensitivity">
            <div className="flex flex-col gap-3">
              {r.sensitivity.map((s: any, i: number) => (
                <div key={i}>
                  <p className="text-xs font-medium">
                    {s.param} {s.error ? <span className="text-neg">— {s.error}</span> : (
                      <Badge variant={s.overfit_spike ? "destructive" : "success"}>{s.verdict}</Badge>
                    )}
                  </p>
                  {s.points && (
                    <table className="mt-1 w-full text-[11px] tabular-nums">
                      <thead className="text-[9px] uppercase text-fg-faint">
                        <tr><th className="text-left">value</th><th className="text-right">×</th>
                          <th className="text-right">Sharpe</th><th className="text-right">Return</th>
                          <th className="text-right">Trades</th></tr>
                      </thead>
                      <tbody>
                        {s.points.map((p: any, j: number) => (
                          <tr key={j} className={cn(p.mult === 1 && "font-semibold text-accent")}>
                            <td className="text-left">{n(p.value, 3)}</td>
                            <td className="text-right">{p.mult}</td>
                            <td className="text-right">{n(p.sharpe_ratio)}</td>
                            <td className="text-right">{pct(p.total_return_pct)}</td>
                            <td className="text-right">{p.total_trades}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Paper Trading
// --------------------------------------------------------------------------

export function AdaptivePaperTradingPage() {
  const runs = usePaperRuns();
  const start = useStartPaperRun();
  const [selected, setSelected] = useState<string | undefined>();
  const [form, setForm] = useState({ underlying: "NIFTY", preset: "balanced", capital: 1_000_000, note: "" });
  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const detail = usePaperRun(selected);
  const run = detail.data as any;
  const actions = usePaperRunAction(selected ?? "x");

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Paper Trading"
        subtitle="Start a run and the engine analyses, selects, sizes, opens a paper position, monitors it and adjusts / exits — logging every decision. Ticks run automatically on the worker during market hours; you can also tick manually."
      />
      <SectionCard title="Start a run">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="flex flex-col gap-1"><Label>Instrument</Label>
            <select className={selCls} value={form.underlying} onChange={(e) => set("underlying", e.target.value)}>
              {UNDERLYINGS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1"><Label>Preset</Label>
            <select className={selCls} value={form.preset} onChange={(e) => set("preset", e.target.value)}>
              {PRESETS.map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1"><Label>Capital (₹)</Label>
            <Input type="number" value={form.capital} onChange={(e) => set("capital", Number(e.target.value))} />
          </div>
          <div className="flex flex-col gap-1"><Label>Note</Label>
            <Input value={form.note} onChange={(e) => set("note", e.target.value)} placeholder="optional" />
          </div>
        </div>
        <div className="mt-3">
          <Button onClick={() => start.mutate({ ...form })} disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Start paper trading"}
          </Button>
        </div>
      </SectionCard>

      <SectionCard title="Runs">
        <div className="flex flex-col gap-2">
          {(runs.data as any)?.runs?.map((r: any) => (
            <button
              key={r.id}
              onClick={() => setSelected(r.id)}
              className={cn(
                "flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm",
                selected === r.id ? "border-accent bg-accent-soft/40" : "border-line hover:bg-elevated/60",
              )}
            >
              <span>
                <span className="font-medium">{r.underlying}</span>{" "}
                <span className="text-xs text-fg-faint">{r.preset} · {r.id.slice(0, 8)}</span>
              </span>
              <span className="flex items-center gap-3 text-xs">
                <Badge variant={r.status === "ACTIVE" ? "success" : "default"}>{r.status}</Badge>
                <span className={cn(r.realized_pnl >= 0 ? "text-pos" : "text-neg")}>{inr(r.realized_pnl)}</span>
                <span className="text-fg-muted">{r.open_positions} open · {r.closed_positions} closed</span>
              </span>
            </button>
          ))}
          {(runs.data as any)?.runs?.length === 0 && <p className="text-xs text-fg-faint">No runs yet.</p>}
        </div>
      </SectionCard>

      {run && (
        <>
          <SectionCard
            title={`Run ${run.id.slice(0, 8)} · ${run.underlying}`}
            actions={
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={run.status !== "ACTIVE" || actions.tick.isPending}
                  onClick={() => actions.tick.mutate()}>
                  {actions.tick.isPending ? "Ticking…" : "Tick now"}
                </Button>
                <Button variant="ghost" size="sm" className="text-neg" disabled={run.status !== "ACTIVE"}
                  onClick={() => actions.stop.mutate()}>Stop</Button>
              </div>
            }
          >
            <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
              <span>Status: <b>{run.status}</b></span>
              <span>Realized P&L: <b className={run.realized_pnl >= 0 ? "text-pos" : "text-neg"}>{inr(run.realized_pnl)}</b></span>
              <span>Capital: <b>{inr(run.capital)}</b></span>
              <span>Last tick: <b>{run.last_tick_at ? new Date(run.last_tick_at).toLocaleString("en-IN") : "–"}</b></span>
            </div>
            {actions.tick.data && (actions.tick.data as any).events && (
              <p className="mt-2 text-[11px] text-fg-muted">
                {(actions.tick.data as any).events.join(" · ") || "no events this tick"}
              </p>
            )}
          </SectionCard>

          <SectionCard title="Positions" bodyClassName="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="bg-surface-2 text-[10px] uppercase text-fg-faint">
                  <tr>
                    {["Opened", "Strategy", "Status", "Lots", "Entry regime", "Target", "Stop", "Last P&L", "Net P&L", "MAE", "MFE", "Adj", "Exit"].map((h) => (
                      <th key={h} className="px-2 py-1.5 text-right first:text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {run.positions.map((p: any) => (
                    <tr key={p.id} className="border-t border-line/50">
                      <td className="px-2 py-1 text-left">{new Date(p.opened_at).toLocaleDateString("en-IN")}</td>
                      <td className="px-2 py-1 text-left">{p.slug}</td>
                      <td className="px-2 py-1 text-left">
                        <Badge variant={p.status === "OPEN" ? "info" : "default"}>{p.status}</Badge>
                      </td>
                      <td className="px-2 py-1 text-right">{p.lots}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{p.entry_regime}</td>
                      <td className="px-2 py-1 text-right text-pos">{inr(p.target_pnl)}</td>
                      <td className="px-2 py-1 text-right text-neg">{inr(p.stop_pnl)}</td>
                      <td className={cn("px-2 py-1 text-right", (p.last_pnl ?? 0) >= 0 ? "text-pos" : "text-neg")}>{inr(p.last_pnl)}</td>
                      <td className={cn("px-2 py-1 text-right", (p.net_pnl ?? 0) >= 0 ? "text-pos" : "text-neg")}>{p.net_pnl == null ? "–" : inr(p.net_pnl)}</td>
                      <td className="px-2 py-1 text-right text-fg-muted">{inr(p.mae)}</td>
                      <td className="px-2 py-1 text-right text-fg-muted">{inr(p.mfe)}</td>
                      <td className="px-2 py-1 text-right">{p.adjustments}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{p.exit_reason ?? "–"}</td>
                    </tr>
                  ))}
                  {run.positions.length === 0 && (
                    <tr><td colSpan={13} className="px-2 py-3 text-center text-fg-faint">No positions yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <DecisionLogTable rows={run.recent_decisions} />
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Decision Log (standalone — pick a run)
// --------------------------------------------------------------------------

export function AdaptiveDecisionLogPage() {
  const runs = usePaperRuns();
  const rows = (runs.data as any)?.runs ?? [];
  const [sel, setSel] = useState<string | undefined>();
  const chosen = sel ?? rows[0]?.id;
  const detail = usePaperRun(chosen);
  const run = detail.data as any;
  const decisions: any[] = useMemo(
    () => run?.recent_decisions ?? [],
    [run],
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Decision Log"
        subtitle="Every decision a paper run has made — entry, no-trade, adjustment, exit — with the regime, action and reason, newest first."
        actions={
          <select className={selCls} value={chosen ?? ""} onChange={(e) => setSel(e.target.value)}>
            <option value="">Select a run</option>
            {rows.map((r: any) => (
              <option key={r.id} value={r.id}>{r.underlying} · {r.id.slice(0, 8)} ({r.status})</option>
            ))}
          </select>
        }
      />
      {!chosen && <p className="text-sm text-fg-faint">Start a paper run to see its decision timeline.</p>}
      {run && (
        <SectionCard title={`${decisions.length} decisions · run ${run.id.slice(0, 8)}`}>
          <ol className="relative ml-3 border-l border-line">
            {decisions.map((dItem: any, i: number) => (
              <li key={i} className="mb-3 ml-4">
                <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-surface bg-accent" />
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-fg-faint">{new Date(dItem.ts).toLocaleString("en-IN")}</span>
                  <Badge variant={dItem.action === "ENTER" ? "success" : dItem.action === "NO_TRADE" ? "warning" : "default"}>
                    {dItem.action}
                  </Badge>
                  <span className="text-fg-muted">{dItem.phase}</span>
                  <span>{dItem.regime}</span>
                  {dItem.strategy && <span className="font-medium">{dItem.strategy}</span>}
                  {dItem.position_pnl != null && (
                    <span className={dItem.position_pnl >= 0 ? "text-pos" : "text-neg"}>{inr(dItem.position_pnl)}</span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-fg-muted">{dItem.reason}</p>
              </li>
            ))}
          </ol>
        </SectionCard>
      )}
    </div>
  );
}
