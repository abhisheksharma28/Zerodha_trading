import { useMemo, useState } from "react";

import type { AdaptiveIntel, QualityIssue } from "@/api/adaptiveOptions";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  useAdaptiveConfig,
  useAdaptiveExpiries,
  useAdaptiveIntel,
} from "@/hooks/useAdaptiveOptions";
import { cn } from "@/lib/utils";

const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] as const;
const PRESETS = ["conservative", "balanced", "aggressive"] as const;

const num = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: d });
const pct = (v: number | null | undefined, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`);
const oiFmt = (v: number | null | undefined) =>
  v == null ? "–" : Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : num(v, 0);

const sevTone: Record<QualityIssue["severity"], "info" | "warning" | "destructive"> = {
  INFO: "info",
  WARNING: "warning",
  ERROR: "destructive",
  CRITICAL: "destructive",
};

function ScoreBar({ value, label, tone }: { value: number; label: string; tone?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="flex justify-between text-[11px] text-fg-faint">
        <span className="uppercase tracking-wide">{label}</span>
        <span className="tabular-nums text-fg-muted">{value.toFixed(0)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-elevated">
        <div
          className={cn("h-full rounded-full", tone ?? "bg-accent")}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

function Kv({ k, v, tone }: { k: string; v: React.ReactNode; tone?: "pos" | "neg" | "muted" }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1 text-sm last:border-0">
      <span className="text-fg-faint">{k}</span>
      <span
        className={cn(
          "text-right font-medium tabular-nums",
          tone === "pos" && "text-pos",
          tone === "neg" && "text-neg",
          tone === "muted" && "text-fg-muted",
        )}
      >
        {v}
      </span>
    </div>
  );
}

function regimeTone(label: string): "success" | "destructive" | "warning" | "info" | "default" {
  if (label.includes("BULLISH") || label === "BREAKOUT") return "success";
  if (label.includes("BEARISH") || label === "BREAKDOWN") return "destructive";
  if (label === "NO_TRADE" || label === "EVENT_RISK") return "warning";
  if (label === "HIGH_VOLATILITY" || label === "REVERSAL") return "info";
  return "default";
}

// --------------------------------------------------------------------------
// controls
// --------------------------------------------------------------------------

function Controls({
  underlying,
  setUnderlying,
  expiry,
  setExpiry,
  preset,
  setPreset,
  onRefresh,
  loading,
}: {
  underlying: string;
  setUnderlying: (v: string) => void;
  expiry: string;
  setExpiry: (v: string) => void;
  preset: string;
  setPreset: (v: string) => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  const { data: exp } = useAdaptiveExpiries(underlying);
  const selCls =
    "h-9 rounded-md border border-line-strong bg-surface px-2.5 text-sm text-fg";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={selCls} value={underlying} onChange={(e) => setUnderlying(e.target.value)}>
        {UNDERLYINGS.map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </select>
      <select className={selCls} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
        <option value="">Nearest expiry</option>
        {(exp?.expiries ?? []).map((e) => (
          <option key={e} value={e}>
            {e}
          </option>
        ))}
      </select>
      <select className={selCls} value={preset} onChange={(e) => setPreset(e.target.value)}>
        {PRESETS.map((p) => (
          <option key={p} value={p}>
            {p[0].toUpperCase() + p.slice(1)}
          </option>
        ))}
      </select>
      <Button variant="secondary" size="sm" onClick={onRefresh} disabled={loading}>
        {loading ? "Analysing…" : "Refresh"}
      </Button>
    </div>
  );
}

// --------------------------------------------------------------------------
// data-quality banner
// --------------------------------------------------------------------------

function DataQualityBanner({ dq }: { dq: AdaptiveIntel["data_quality"] }) {
  const all = [...dq.issues, ...dq.underlying_issues];
  if (dq.ok && all.length === 0) return null;
  return (
    <Card className={cn(!dq.ok ? "border-red-500/40 bg-red-500/5" : "border-amber-500/40 bg-amber-500/5")}>
      <CardContent className="space-y-1.5 py-3 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-semibold">
            Data quality {dq.score.toFixed(0)}/100 — {dq.ok ? "usable" : "gate failed"}
          </span>
          {!dq.ok && (
            <span className="text-neg">
              The engine will not issue a decision; readings below are for diagnosis only.
            </span>
          )}
        </div>
        {all.map((i, idx) => (
          <div key={idx} className="flex items-start gap-2">
            <Badge variant={sevTone[i.severity]} className="shrink-0">
              {i.severity}
            </Badge>
            <span className="text-fg-muted">{i.detail}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------
// the shared intelligence view
// --------------------------------------------------------------------------

function IntelligenceView({ compact }: { compact?: boolean }) {
  const [underlying, setUnderlying] = useState<string>("NIFTY");
  const [expiry, setExpiry] = useState<string>("");
  const [preset, setPreset] = useState<string>("balanced");
  const [showChain, setShowChain] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const q = useAdaptiveIntel({ underlying, expiry: expiry || undefined, preset });
  const d = q.data;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={compact ? "Adaptive Options" : "Market Intelligence"}
        subtitle={
          compact
            ? "One read of the market, positioning, volatility and the resulting regime."
            : "Every engine's output for the selected underlying and expiry, from live data + stored history."
        }
        actions={
          <Controls
            underlying={underlying}
            setUnderlying={setUnderlying}
            expiry={expiry}
            setExpiry={setExpiry}
            preset={preset}
            setPreset={setPreset}
            onRefresh={() => q.refetch()}
            loading={q.isFetching}
          />
        }
      />

      {q.isLoading && <p className="text-sm text-fg-faint">Running the pipeline…</p>}
      {q.isError && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="py-3 text-sm text-neg">{(q.error as Error).message}</CardContent>
        </Card>
      )}
      {d && !d.available && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="py-3 text-sm">
            <span className="font-medium">Analysis unavailable.</span> {d.reason}
            {d.reason?.toLowerCase().includes("broker") && (
              <p className="mt-1 text-fg-muted">
                Connect a Zerodha session on the Broker page — the engine needs the live option
                chain and the underlying's candles.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {d?.available && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <StatCard
              label="Regime"
              value={d.regime.label.replace(/_/g, " ")}
              valueClassName="text-base"
              delta={`conf ${d.regime.confidence.toFixed(0)} · risk ${d.regime.transition_risk.toFixed(0)}`}
              deltaTone={d.regime.direction === "BULLISH" ? "pos" : d.regime.direction === "BEARISH" ? "neg" : "muted"}
            />
            <StatCard
              label="Weighted PCR"
              value={num(d.pcr.weighted_pcr)}
              delta={`${d.pcr.state.replace(/_/g, " ")}${d.pcr.transition !== "STABLE" ? ` · ${d.pcr.transition.replace(/_/g, " ").toLowerCase()}` : ""}`}
              deltaTone={d.pcr.weighted_pcr >= 1.1 ? "pos" : d.pcr.weighted_pcr <= 0.85 ? "neg" : "muted"}
            />
            <StatCard
              label="IV rank / class"
              value={d.volatility.iv_rank == null ? d.volatility.iv_class.replace(/_/g, " ") : d.volatility.iv_rank.toFixed(0)}
              delta={`ATM IV ${pct(d.volatility.atm_iv)} · selling ${d.volatility.vol_selling_verdict.toLowerCase()}`}
              deltaTone={d.volatility.vol_selling_verdict === "FAVOURABLE" ? "pos" : d.volatility.vol_selling_verdict === "UNFAVOURABLE" ? "neg" : "muted"}
            />
            <StatCard
              label="Expected move"
              value={d.expected_move.points == null ? "–" : `±${num(d.expected_move.points, 0)}`}
              delta={
                d.expected_move.current_vs_expected == null
                  ? `${num(d.expected_move.lower, 0)} – ${num(d.expected_move.upper, 0)}`
                  : `used ${(d.expected_move.current_vs_expected * 100).toFixed(0)}% today`
              }
              deltaTone={(d.expected_move.current_vs_expected ?? 0) > 1 ? "neg" : "muted"}
            />
            <StatCard
              label="Confidence"
              value={d.confidence.score.toFixed(0)}
              delta={d.confidence.band}
              deltaTone={d.confidence.score >= 70 ? "pos" : d.confidence.score < 40 ? "neg" : "muted"}
            />
            <StatCard
              label="Data quality"
              value={d.data_quality.score.toFixed(0)}
              delta={d.data_quality.ok ? "gate passed" : "gate failed"}
              deltaTone={d.data_quality.ok ? "pos" : "neg"}
            />
          </div>

          <DataQualityBanner dq={d.data_quality} />

          {/* plain-English summary */}
          <SectionCard title="What the engine sees">
            <ul className="space-y-1.5 text-sm">
              {d.summary.map((s, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-accent">·</span>
                  <span className={cn(i === 0 && !d.data_quality.ok && "text-neg")}>{s}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] text-fg-faint">
              {d.underlying} · {d.expiry} · {d.dte} DTE · spot {num(d.spot, 1)} · as of{" "}
              {new Date(d.as_of).toLocaleString("en-IN")} · history {d.history_len} snapshots ·
              preset {d.config.preset}
            </p>
          </SectionCard>

          {!compact && (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <SectionCard title="Market regime">
                  <div className="mb-3 flex items-center gap-2">
                    <Badge variant={regimeTone(d.regime.label)}>{d.regime.label.replace(/_/g, " ")}</Badge>
                    <Badge variant="default">{d.regime.direction}</Badge>
                    <Badge variant="default">{d.regime.vol_class} vol</Badge>
                  </div>
                  <div className="space-y-2">
                    <ScoreBar label="Confidence" value={d.regime.confidence} />
                    <ScoreBar label="Stability" value={d.regime.stability} tone="bg-pos" />
                    <ScoreBar label="Transition risk" value={d.regime.transition_risk} tone="bg-neg" />
                  </div>
                  <ul className="mt-3 space-y-1 text-xs text-fg-muted">
                    {d.regime.drivers.map((x, i) => (
                      <li key={i}>— {x}</li>
                    ))}
                  </ul>
                  <div className="mt-3">
                    {Object.entries(d.regime.contributing).map(([k, v]) => (
                      <Kv key={k} k={k.replace(/_/g, " ")} v={v} tone="muted" />
                    ))}
                  </div>
                </SectionCard>

                <SectionCard title="PCR intelligence">
                  <div className="grid grid-cols-2 gap-x-4">
                    <Kv k="OI PCR" v={num(d.pcr.oi_pcr)} />
                    <Kv k="Volume PCR" v={num(d.pcr.volume_pcr)} />
                    <Kv k="ΔOI PCR" v={d.pcr.chg_oi_pcr == null ? "–" : num(d.pcr.chg_oi_pcr)} />
                    <Kv k="ATM PCR" v={num(d.pcr.atm_pcr)} />
                    <Kv k="Near-ATM PCR" v={num(d.pcr.near_atm_pcr)} />
                    <Kv k="Weighted PCR" v={num(d.pcr.weighted_pcr)} />
                    <Kv k="State" v={d.pcr.state.replace(/_/g, " ")} />
                    <Kv
                      k="Transition"
                      v={`${d.pcr.transition.replace(/_/g, " ")}${d.pcr.transition_confirmed ? " ✓" : ""}`}
                    />
                    <Kv k="Percentile" v={d.pcr.weighted_stat.percentile == null ? "–" : pct(d.pcr.weighted_stat.percentile, 0)} />
                    <Kv k="Z-score" v={d.pcr.weighted_stat.zscore == null ? "–" : num(d.pcr.weighted_stat.zscore)} />
                    <Kv k="Slope" v={d.pcr.weighted_stat.slope == null ? "–" : num(d.pcr.weighted_stat.slope, 4)} />
                    <Kv k="Divergence vs price" v={d.pcr.price_divergence.replace(/_/g, " ")} />
                  </div>
                  {d.pcr.notes.map((nn, i) => (
                    <p key={i} className="mt-2 text-[11px] text-fg-faint">
                      {nn}
                    </p>
                  ))}
                </SectionCard>

                <SectionCard title="Options positioning">
                  <div className="space-y-2">
                    <ScoreBar label="Put writing strength" value={d.positioning.put_writing_strength} tone="bg-pos" />
                    <ScoreBar label="Call writing strength" value={d.positioning.call_writing_strength} tone="bg-neg" />
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-x-4">
                    <Kv k="Price + OI" v={d.positioning.price_oi_state.replace(/_/g, " ")} />
                    <Kv k="OI migration" v={d.positioning.oi_migration} />
                    <Kv k="Put support" v={num(d.positioning.put_support, 0)} tone="pos" />
                    <Kv k="Call resistance" v={num(d.positioning.call_resistance, 0)} tone="neg" />
                    <Kv k="OI concentration" v={pct(d.positioning.oi_concentration, 0)} />
                    <Kv k="Max pain (info)" v={num(d.positioning.max_pain, 0)} tone="muted" />
                  </div>
                  <div className="mt-3 text-xs">
                    <p className="mb-1 text-fg-faint">OI walls</p>
                    {d.positioning.oi_walls.map((w, i) => (
                      <div key={i} className="flex justify-between border-b border-line/60 py-0.5 last:border-0">
                        <span className={w.kind === "PUT_WALL" ? "text-pos" : "text-neg"}>
                          {w.kind === "PUT_WALL" ? "Put" : "Call"} {num(w.strike, 0)}
                        </span>
                        <span className="tabular-nums text-fg-muted">{oiFmt(w.oi)}</span>
                      </div>
                    ))}
                  </div>
                  {d.positioning.notes.map((nn, i) => (
                    <p key={i} className="mt-2 text-[11px] text-fg-faint">
                      {nn}
                    </p>
                  ))}
                </SectionCard>

                <SectionCard title="Volatility">
                  <div className="grid grid-cols-2 gap-x-4">
                    <Kv k="ATM IV" v={pct(d.volatility.atm_iv)} />
                    <Kv k="Class" v={d.volatility.iv_class.replace(/_/g, " ")} />
                    <Kv k="IV rank" v={d.volatility.iv_rank == null ? "pending" : d.volatility.iv_rank.toFixed(0)} />
                    <Kv k="IV percentile" v={d.volatility.iv_percentile == null ? "pending" : d.volatility.iv_percentile.toFixed(0)} />
                    <Kv k="IV skew (P−C)" v={pct(d.volatility.iv_skew)} />
                    <Kv k="Term structure" v={d.volatility.term_structure} />
                    <Kv k="Realized vol" v={pct(d.volatility.realized_vol)} />
                    <Kv k="IV − RV" v={pct(d.volatility.iv_minus_rv)} tone={(d.volatility.iv_minus_rv ?? 0) > 0 ? "pos" : "neg"} />
                  </div>
                  <div className="mt-3">
                    <ScoreBar
                      label="Volatility-selling score"
                      value={d.volatility.vol_selling_score}
                      tone={d.volatility.vol_selling_verdict === "FAVOURABLE" ? "bg-pos" : d.volatility.vol_selling_verdict === "UNFAVOURABLE" ? "bg-neg" : "bg-accent"}
                    />
                    <p className="mt-1 text-xs text-fg-muted">
                      Verdict: <span className="font-medium">{d.volatility.vol_selling_verdict}</span> — high IV alone is
                      not enough; this also weighs IV-vs-realized, trend strength, DTE and IV path.
                    </p>
                  </div>
                  {d.volatility.notes.map((nn, i) => (
                    <p key={i} className="mt-2 text-[11px] text-fg-faint">
                      {nn}
                    </p>
                  ))}
                </SectionCard>

                <SectionCard title="Expected move">
                  <div className="grid grid-cols-2 gap-x-4">
                    <Kv k="Headline (±)" v={num(d.expected_move.points, 0)} />
                    <Kv k="As % of spot" v={d.expected_move.pct == null ? "–" : `${d.expected_move.pct.toFixed(2)}%`} />
                    <Kv k="Upper" v={num(d.expected_move.upper, 0)} tone="pos" />
                    <Kv k="Lower" v={num(d.expected_move.lower, 0)} tone="neg" />
                    <Kv k="Straddle method" v={num(d.expected_move.by_method.straddle, 0)} />
                    <Kv k="IV method" v={num(d.expected_move.by_method.iv, 0)} />
                    <Kv k="ATR method" v={num(d.expected_move.by_method.atr, 0)} />
                    <Kv k="Today vs expected" v={d.expected_move.current_vs_expected == null ? "–" : `${(d.expected_move.current_vs_expected * 100).toFixed(0)}%`} />
                  </div>
                  {d.expected_move.notes.map((nn, i) => (
                    <p key={i} className="mt-2 text-[11px] text-fg-faint">
                      {nn}
                    </p>
                  ))}
                </SectionCard>

                <SectionCard title="Price action & structure">
                  <div className="grid grid-cols-2 gap-x-4">
                    <Kv k="Trend" v={`${d.market_intelligence.trend_direction} (${d.market_intelligence.trend_strength.toFixed(0)})`} />
                    <Kv k="Structure" v={d.market_intelligence.market_structure.replace(/_/g, " ")} />
                    <Kv k="EMA stack" v={d.market_intelligence.ema_stack} />
                    <Kv k="Momentum" v={d.market_intelligence.momentum} />
                    <Kv k="VWAP" v={`${d.market_intelligence.above_vwap ? "above" : "below"} (${d.market_intelligence.vwap_distance_pct.toFixed(2)}%)`} />
                    <Kv k="RSI" v={num(d.market_intelligence.rsi, 0)} />
                    <Kv k="ADX" v={num(d.market_intelligence.adx, 0)} />
                    <Kv k="ATR %" v={d.market_intelligence.atr_pct == null ? "–" : `${d.market_intelligence.atr_pct.toFixed(2)}%`} />
                    <Kv k="Rel volume" v={num(d.market_intelligence.rel_volume)} />
                    <Kv k="Volume trend" v={d.market_intelligence.volume_trend} />
                    <Kv k="Support" v={num(d.market_intelligence.support, 0)} tone="pos" />
                    <Kv k="Resistance" v={num(d.market_intelligence.resistance, 0)} tone="neg" />
                  </div>
                </SectionCard>
              </div>

              {/* progressive disclosure: raw chain */}
              <SectionCard
                title="Option chain snapshot"
                actions={
                  <Button variant="ghost" size="sm" onClick={() => setShowChain((s) => !s)}>
                    {showChain ? "Hide" : `Show ${d.chain.rows.length} strikes`}
                  </Button>
                }
                bodyClassName={showChain ? "p-0" : undefined}
              >
                {!showChain ? (
                  <p className="text-xs text-fg-faint">
                    ATM {num(d.chain.atm, 0)} · step {num(d.chain.strike_step, 0)} · total call OI{" "}
                    {oiFmt(d.positioning.total_call_oi)} · total put OI {oiFmt(d.positioning.total_put_oi)}
                  </p>
                ) : (
                  <div className="max-h-[420px] overflow-auto">
                    <table className="w-full text-xs tabular-nums">
                      <thead className="sticky top-0 bg-surface-2 text-[10px] uppercase text-fg-faint">
                        <tr>
                          <th className="px-2 py-1.5 text-right">Call OI</th>
                          <th className="px-2 py-1.5 text-right">Call ΔOI</th>
                          <th className="px-2 py-1.5 text-right">Call IV</th>
                          <th className="px-2 py-1.5 text-center">Strike</th>
                          <th className="px-2 py-1.5 text-left">Put IV</th>
                          <th className="px-2 py-1.5 text-left">Put ΔOI</th>
                          <th className="px-2 py-1.5 text-left">Put OI</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.chain.rows.map((r) => (
                          <tr
                            key={r.strike}
                            className={cn(
                              "border-b border-line/50",
                              r.strike === d.chain.atm && "bg-accent-soft/40",
                            )}
                          >
                            <td className="px-2 py-1 text-right">{oiFmt(r.call_oi)}</td>
                            <td className={cn("px-2 py-1 text-right", r.call_chg_oi >= 0 ? "text-pos" : "text-neg")}>
                              {oiFmt(r.call_chg_oi)}
                            </td>
                            <td className="px-2 py-1 text-right text-fg-muted">{pct(r.call_iv)}</td>
                            <td className="px-2 py-1 text-center font-medium">{num(r.strike, 0)}</td>
                            <td className="px-2 py-1 text-left text-fg-muted">{pct(r.put_iv)}</td>
                            <td className={cn("px-2 py-1 text-left", r.put_chg_oi >= 0 ? "text-pos" : "text-neg")}>
                              {oiFmt(r.put_chg_oi)}
                            </td>
                            <td className="px-2 py-1 text-left">{oiFmt(r.put_oi)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </SectionCard>

              {/* resolved config (advanced) */}
              <SectionCard
                title="Resolved configuration"
                actions={
                  <Button variant="ghost" size="sm" onClick={() => setShowAdvanced((s) => !s)}>
                    {showAdvanced ? "Hide" : "Show"}
                  </Button>
                }
              >
                {showAdvanced ? (
                  <pre className="max-h-72 overflow-auto rounded bg-elevated p-3 text-[11px] text-fg-muted">
                    {JSON.stringify(d.config, null, 2)}
                  </pre>
                ) : (
                  <p className="text-xs text-fg-faint">
                    Preset <span className="font-medium">{d.config.preset}</span>. Every threshold and
                    weight is overridable — the Settings section (later phase) will expose them; today
                    the API accepts an <code>overrides</code> object.
                  </p>
                )}
              </SectionCard>
            </>
          )}
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// exported pages
// --------------------------------------------------------------------------

export function AdaptiveDashboardPage() {
  return <IntelligenceView compact />;
}

export function AdaptiveMarketIntelligencePage() {
  return <IntelligenceView />;
}

export function AdaptiveRiskGreeksPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [preset, setPreset] = useState("balanced");
  const q = useAdaptiveIntel({ underlying, expiry: expiry || undefined, preset });
  const d = q.data;
  const rows = useMemo(() => d?.available ? d.greeks.per_strike : [], [d]);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Risk & Greeks"
        subtitle="Per-strike and ATM greeks from the live chain (Black-Scholes on chain IV). Portfolio / position-level greeks arrive with the Strategy Engine phase."
        actions={
          <Controls
            underlying={underlying}
            setUnderlying={setUnderlying}
            expiry={expiry}
            setExpiry={setExpiry}
            preset={preset}
            setPreset={setPreset}
            onRefresh={() => q.refetch()}
            loading={q.isFetching}
          />
        }
      />
      {d?.available === false && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="py-3 text-sm">{d.reason}</CardContent>
        </Card>
      )}
      {d?.available && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <SectionCard title="ATM call greeks">
              {Object.entries(d.greeks.atm_call).map(([k, v]) => (
                <Kv key={k} k={k} v={num(v, k === "gamma" ? 6 : 4)} />
              ))}
            </SectionCard>
            <SectionCard title="ATM put greeks">
              {Object.entries(d.greeks.atm_put).map(([k, v]) => (
                <Kv key={k} k={k} v={num(v, k === "gamma" ? 6 : 4)} />
              ))}
            </SectionCard>
          </div>
          <SectionCard title="Greek-based warnings">
            <ul className="space-y-1 text-sm">
              {d.greeks.gamma_zone && (
                <li>
                  <Badge variant="warning">GAMMA ZONE</Badge> Aggregate gamma peaks between{" "}
                  {num(d.greeks.gamma_zone[0], 0)} and {num(d.greeks.gamma_zone[1], 0)} — pin / whip risk there.
                </li>
              )}
              {d.dte <= 2 && (
                <li>
                  <Badge variant="destructive">EXPIRY RISK</Badge> {d.dte} DTE — gamma and theta move
                  fast intrabar; reduce size and adjustment frequency.
                </li>
              )}
              {d.volatility.iv_change != null && d.volatility.iv_change > 0.015 && (
                <li>
                  <Badge variant="warning">VEGA</Badge> IV is expanding — short-vega structures are
                  marking against you.
                </li>
              )}
              {d.greeks.notes.map((nn, i) => (
                <li key={i} className="text-xs text-fg-faint">
                  {nn}
                </li>
              ))}
            </ul>
          </SectionCard>
          <SectionCard title="Per-strike greeks" bodyClassName="p-0">
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="sticky top-0 bg-surface-2 text-[10px] uppercase text-fg-faint">
                  <tr>
                    <th className="px-2 py-1.5 text-right">C Δ</th>
                    <th className="px-2 py-1.5 text-right">C Γ</th>
                    <th className="px-2 py-1.5 text-right">C Θ</th>
                    <th className="px-2 py-1.5 text-right">C V</th>
                    <th className="px-2 py-1.5 text-center">Strike</th>
                    <th className="px-2 py-1.5 text-left">P Δ</th>
                    <th className="px-2 py-1.5 text-left">P Γ</th>
                    <th className="px-2 py-1.5 text-left">P Θ</th>
                    <th className="px-2 py-1.5 text-left">P V</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.strike}
                      className={cn("border-b border-line/50", r.strike === d.chain.atm && "bg-accent-soft/40")}
                    >
                      <td className="px-2 py-1 text-right">{num(r.call.delta, 3)}</td>
                      <td className="px-2 py-1 text-right text-fg-muted">{num(r.call.gamma, 5)}</td>
                      <td className="px-2 py-1 text-right text-neg">{num(r.call.theta, 1)}</td>
                      <td className="px-2 py-1 text-right text-fg-muted">{num(r.call.vega, 2)}</td>
                      <td className="px-2 py-1 text-center font-medium">{num(r.strike, 0)}</td>
                      <td className="px-2 py-1 text-left">{num(r.put.delta, 3)}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{num(r.put.gamma, 5)}</td>
                      <td className="px-2 py-1 text-left text-neg">{num(r.put.theta, 1)}</td>
                      <td className="px-2 py-1 text-left text-fg-muted">{num(r.put.vega, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

export function AdaptiveSettingsPage() {
  const { data } = useAdaptiveConfig();
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Adaptive Options — Settings"
        subtitle="Beginner presets and the full list of overridable parameters. The analysis endpoint accepts any of these as an overrides object; a form editor lands with the Strategy Engine phase."
      />
      {data && (
        <>
          <SectionCard title="Presets">
            <div className="grid gap-4 md:grid-cols-3">
              {Object.entries(data.presets).map(([name, cfg]) => (
                <div key={name} className="rounded-md border border-line p-3">
                  <p className="mb-2 text-sm font-semibold capitalize">{name}</p>
                  <div className="space-y-0.5 text-xs">
                    {Object.entries(cfg)
                      .filter(([k]) => k !== "risk_profile")
                      .slice(0, 10)
                      .map(([k, v]) => (
                        <div key={k} className="flex justify-between">
                          <span className="text-fg-faint">{k}</span>
                          <span className="tabular-nums text-fg-muted">{String(v)}</span>
                        </div>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
          <SectionCard title="All overridable fields">
            <p className="mb-2 text-xs text-fg-faint">{data.note}</p>
            <div className="flex flex-wrap gap-1.5">
              {data.fields.map((f) => (
                <code key={f} className="rounded bg-elevated px-1.5 py-0.5 text-[11px] text-fg-muted">
                  {f}
                </code>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

const PHASE_INFO: Record<string, { phase: string; what: string }> = {
  "strategy-engine": {
    phase: "Phase 8–9",
    what: "Strategy library (defined-risk templates) + the adaptive selection engine that ranks strategies by a configurable Suitability Score from regime, PCR, positioning, volatility, expected move and liquidity. NO_TRADE is a first-class output.",
  },
  "strategy-builder": {
    phase: "Phase 10",
    what: "Intelligent strike selection (delta / expected-move / probability / premium / OI-wall / S-R / IV / liquidity methods) with ranked strike combinations and their payoff, POP, margin and greeks.",
  },
  backtesting: {
    phase: "Phase 13–14",
    what: "Simple and Advanced modes over NSE F&O bhavcopy (real daily OI) with a synthetic vol-surface fallback for intraday mechanics. Full realism: brokerage / STT / GST / stamp / slippage, no look-ahead. Per-regime and per-strategy attribution.",
  },
  validation: {
    phase: "Phase 15",
    what: "Walk-forward, out-of-sample, parameter sensitivity, Monte Carlo (jitter entry / slippage / fills) and an overfitting flag — reusing the platform's existing robustness suite.",
  },
  "paper-trading": {
    phase: "Phase 16",
    what: "The same decision engine, live: analyse → select → pick strikes → open a paper position → monitor → adjust legs → exit, with a running decision log and P&L / greeks.",
  },
  comparison: {
    phase: "Phase 9",
    what: "Side-by-side Suitability, Probability of Profit, max profit / loss, margin, greeks, expected value and risk score for a chosen set of strategies against the current market — so you can see why one is picked over another.",
  },
  "decision-log": {
    phase: "Phase 16",
    what: "Every entry / no-trade / adjustment / exit with its trigger, reason, expected effect and risk impact, on a timeline you can replay.",
  },
};

export function AdaptivePhasePendingPage({ section }: { section: string }) {
  const info = PHASE_INFO[section] ?? { phase: "Later phase", what: "Not built yet." };
  const title = section
    .split("-")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={`Adaptive Options — ${title}`} subtitle="Not yet built — here's exactly what it will do." />
      <Card>
        <CardContent className="space-y-3 py-5">
          <Badge variant="info">{info.phase}</Badge>
          <p className="max-w-2xl text-sm text-fg-muted">{info.what}</p>
          <p className="text-xs text-fg-faint">
            Phases 0–7 (data quality, market intelligence, PCR, positioning, volatility, greeks,
            expected move, confidence, regime) are live now — see <b>Market Intelligence</b> and{" "}
            <b>Risk &amp; Greeks</b>. This section is intentionally not a mock: no buttons here call
            anything until the phase ships.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
