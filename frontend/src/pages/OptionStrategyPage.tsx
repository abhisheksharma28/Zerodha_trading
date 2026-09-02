import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Plus, Trash2 } from "lucide-react";

import { optionsApi, type OptionChain } from "@/api/options";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Action = "buy" | "sell";
type OptType = "CE" | "PE";
interface Leg {
  id: number;
  action: Action;
  type: OptType;
  strike: number;
  lots: number;
  premium: number;
}

// Default F&O lot sizes (editable in the UI — exchange revises these).
const LOT_SIZE: Record<string, number> = {
  NIFTY: 75,
  BANKNIFTY: 30,
  FINNIFTY: 65,
  MIDCPNIFTY: 120,
  NIFTYNXT50: 25,
};

const PRESET_GROUPS: {
  outlook: string;
  tone: "pos" | "neg" | "muted";
  presets: { key: string; label: string; hint: string }[];
}[] = [
  {
    outlook: "Bullish",
    tone: "pos",
    presets: [
      { key: "long_call", label: "Long Call", hint: "Buy 1 ATM call" },
      { key: "bull_call", label: "Bull Call Spread", hint: "Buy ATM / sell OTM call" },
      { key: "bull_put", label: "Bull Put Spread", hint: "Sell ATM / buy OTM put (credit)" },
    ],
  },
  {
    outlook: "Bearish",
    tone: "neg",
    presets: [
      { key: "long_put", label: "Long Put", hint: "Buy 1 ATM put" },
      { key: "bear_put", label: "Bear Put Spread", hint: "Buy ATM / sell OTM put" },
      { key: "bear_call", label: "Bear Call Spread", hint: "Sell ATM / buy OTM call (credit)" },
    ],
  },
  {
    outlook: "Neutral",
    tone: "muted",
    presets: [
      { key: "iron_condor", label: "Iron Condor", hint: "Sell OTM strangle, buy wings" },
      { key: "iron_fly", label: "Iron Butterfly", hint: "Sell ATM straddle, buy wings" },
      { key: "short_straddle", label: "Short Straddle", hint: "Sell ATM call + put (credit)" },
    ],
  },
  {
    outlook: "Volatile",
    tone: "muted",
    presets: [
      { key: "long_straddle", label: "Long Straddle", hint: "Buy ATM call + put" },
      { key: "long_strangle", label: "Long Strangle", hint: "Buy OTM call + put" },
    ],
  },
  {
    outlook: "Ratio / HNI",
    tone: "muted",
    presets: [
      {
        key: "hni_132_call_ratio",
        label: "NIFTY Monthly HNI (1:3:2)",
        hint: "Buy 1 A CE / Sell 3 B CE / Buy 2 C CE — ~300pt OTM, 300pt spacing",
      },
      {
        key: "broken_wing_call_fly",
        label: "Broken-Wing Call Butterfly",
        hint: "Buy 1 ATM CE / Sell 2 mid CE / Buy 1 far CE (unequal wings)",
      },
      {
        key: "call_ratio_spread",
        label: "Call Ratio Spread (1:2)",
        hint: "Buy 1 ATM CE / Sell 2 OTM CE" ,
      },
    ],
  },
];

const n = (v: number | null | undefined, d = 2) =>
  v == null || !isFinite(v) ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: d });
const rupee = (v: number) =>
  `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function inferStep(strikes: number[]): number {
  if (strikes.length < 2) return 50;
  const diffs: number[] = [];
  for (let i = 1; i < strikes.length; i++) diffs.push(strikes[i] - strikes[i - 1]);
  diffs.sort((a, b) => a - b);
  return diffs[Math.floor(diffs.length / 2)] || 50;
}

function nearestStrike(strikes: number[], target: number): number {
  return strikes.reduce((best, s) => (Math.abs(s - target) < Math.abs(best - target) ? s : best), strikes[0]);
}

function premiumAt(chain: Extract<OptionChain, { available: true }>, strike: number, type: OptType): number {
  const row = chain.rows.find((r) => r.strike === strike);
  const leg = type === "CE" ? row?.call : row?.put;
  return leg?.ltp ?? 0;
}

function buildPreset(
  key: string,
  chain: Extract<OptionChain, { available: true }>,
): Leg[] {
  const strikes = chain.rows.map((r) => r.strike).sort((a, b) => a - b);
  if (strikes.length === 0) return [];
  const step = inferStep(strikes);
  const atm = chain.atm_strike ?? nearestStrike(strikes, chain.spot ?? strikes[Math.floor(strikes.length / 2)]);
  const k = (mult: number) => nearestStrike(strikes, atm + mult * step);
  let id = 0;
  const mk = (action: Action, type: OptType, strike: number, lots = 1): Leg => ({
    id: id++,
    action,
    type,
    strike,
    lots,
    premium: premiumAt(chain, strike, type),
  });

  switch (key) {
    case "long_call":
      return [mk("buy", "CE", k(0))];
    case "long_put":
      return [mk("buy", "PE", k(0))];
    case "bull_call":
      return [mk("buy", "CE", k(0)), mk("sell", "CE", k(2))];
    case "bull_put":
      return [mk("sell", "PE", k(0)), mk("buy", "PE", k(-2))];
    case "bear_put":
      return [mk("buy", "PE", k(0)), mk("sell", "PE", k(-2))];
    case "bear_call":
      return [mk("sell", "CE", k(0)), mk("buy", "CE", k(2))];
    case "iron_condor":
      return [
        mk("sell", "PE", k(-2)),
        mk("buy", "PE", k(-4)),
        mk("sell", "CE", k(2)),
        mk("buy", "CE", k(4)),
      ];
    case "iron_fly":
      return [
        mk("sell", "CE", k(0)),
        mk("sell", "PE", k(0)),
        mk("buy", "CE", k(3)),
        mk("buy", "PE", k(-3)),
      ];
    case "short_straddle":
      return [mk("sell", "CE", k(0)), mk("sell", "PE", k(0))];
    case "long_straddle":
      return [mk("buy", "CE", k(0)), mk("buy", "PE", k(0))];
    case "long_strangle":
      return [mk("buy", "CE", k(2)), mk("buy", "PE", k(-2))];
    case "hni_132_call_ratio": {
      // ~300pt OTM for A, then ~300pt spacing A→B→C. On a 50pt grid that is
      // 6 / 12 / 18 steps above ATM. Lots 1 : 3 : 2 (net short the middle).
      const g = Math.max(1, Math.round(300 / step));
      return [
        mk("buy", "CE", k(g), 1),
        mk("sell", "CE", k(2 * g), 3),
        mk("buy", "CE", k(3 * g), 2),
      ];
    }
    case "broken_wing_call_fly":
      // unequal wings: 2 steps up to the body, 5 steps up to the far wing
      return [mk("buy", "CE", k(0), 1), mk("sell", "CE", k(2), 2), mk("buy", "CE", k(5), 1)];
    case "call_ratio_spread":
      return [mk("buy", "CE", k(0), 1), mk("sell", "CE", k(3), 2)];
    default:
      return [];
  }
}

function legPayoff(leg: Leg, spot: number, lotSize: number): number {
  const intrinsic = leg.type === "CE" ? Math.max(0, spot - leg.strike) : Math.max(0, leg.strike - spot);
  const dir = leg.action === "buy" ? 1 : -1;
  const qty = leg.lots * lotSize;
  const entry = -dir * leg.premium * qty; // buy pays premium, sell receives
  return dir * intrinsic * qty + entry;
}

interface Analysis {
  netPremium: number;
  curve: { spot: number; pnl: number }[];
  maxProfit: number | null;
  maxLoss: number | null;
  breakevens: number[];
}

function analyse(legs: Leg[], lotSize: number, spot: number): Analysis | null {
  if (legs.length === 0) return null;
  const netPremium = legs.reduce(
    (s, l) => s + (l.action === "buy" ? -1 : 1) * l.premium * l.lots * lotSize,
    0,
  );
  const lo = Math.max(1, spot * 0.7);
  const hi = spot * 1.3;
  const steps = 240;
  const curve: { spot: number; pnl: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const s = lo + ((hi - lo) * i) / steps;
    const pnl = legs.reduce((acc, l) => acc + legPayoff(l, s, lotSize), 0);
    curve.push({ spot: Math.round(s), pnl: Math.round(pnl) });
  }
  const pnls = curve.map((p) => p.pnl);
  const maxAtEdge = pnls[pnls.length - 1];
  const minAtEdge = pnls[0];
  let maxProfit: number | null = Math.max(...pnls);
  let maxLoss: number | null = Math.min(...pnls);
  // detect unbounded tails (still rising / falling at the sampled edges)
  if (pnls[pnls.length - 1] === maxProfit && maxAtEdge > pnls[pnls.length - 2]) maxProfit = null;
  if (pnls[0] === maxLoss && minAtEdge < pnls[1]) maxLoss = null;

  const breakevens: number[] = [];
  for (let i = 1; i < curve.length; i++) {
    const a = curve[i - 1];
    const b = curve[i];
    if ((a.pnl <= 0 && b.pnl >= 0) || (a.pnl >= 0 && b.pnl <= 0)) {
      const t = a.pnl === b.pnl ? 0 : Math.abs(a.pnl) / (Math.abs(a.pnl) + Math.abs(b.pnl));
      breakevens.push(Math.round(a.spot + t * (b.spot - a.spot)));
    }
  }
  return { netPremium, curve, maxProfit, maxLoss, breakevens };
}

export default function OptionStrategyPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [underlying, setUnderlyingState] = useState(
    () => (searchParams.get("underlying") || "NIFTY").toUpperCase(),
  );
  const [expiryPick, setExpiryPick] = useState("");
  const [legs, setLegs] = useState<Leg[]>([]);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [lotSizeOverride, setLotSizeOverride] = useState<number | null>(null);

  const setUnderlying = (u: string) => {
    setUnderlyingState(u);
    setExpiryPick("");
    setLegs([]);
    setActivePreset(null);
    setLotSizeOverride(null);
    setSearchParams((prev) => {
      prev.set("underlying", u);
      return prev;
    });
  };

  const { data: underlyings } = useQuery({
    queryKey: ["opt", "underlyings"],
    queryFn: () => optionsApi.underlyings(),
    staleTime: 5 * 60_000,
  });
  const { data: expiries } = useQuery({
    queryKey: ["opt", "expiries", underlying],
    queryFn: () => optionsApi.expiries(underlying),
    staleTime: 5 * 60_000,
  });
  const expiry = expiryPick && expiries?.includes(expiryPick) ? expiryPick : (expiries?.[0] ?? "");

  const { data: chain } = useQuery({
    queryKey: ["opt", "chain", underlying, expiry],
    queryFn: () => optionsApi.chain(underlying, expiry),
    enabled: !!expiry,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });

  const live = chain?.available ? chain : null;
  const lotSize = lotSizeOverride ?? LOT_SIZE[underlying] ?? 1;
  const spot = live?.spot ?? live?.atm_strike ?? 0;
  const strikes = useMemo(
    () => (live ? live.rows.map((r) => r.strike).sort((a, b) => a - b) : []),
    [live],
  );

  const applyPreset = (key: string) => {
    if (!live) return;
    setLegs(buildPreset(key, live));
    setActivePreset(key);
  };

  const updateLeg = (id: number, patch: Partial<Leg>) =>
    setLegs((ls) =>
      ls.map((l) => {
        if (l.id !== id) return l;
        const next = { ...l, ...patch };
        // re-pull premium when the strike or option type changes
        if (live && (patch.strike != null || patch.type != null)) {
          next.premium = premiumAt(live, next.strike, next.type);
        }
        return next;
      }),
    );

  const addLeg = () => {
    const strike = live?.atm_strike ?? strikes[Math.floor(strikes.length / 2)] ?? 0;
    setLegs((ls) => [
      ...ls,
      {
        id: (ls.at(-1)?.id ?? -1) + 1,
        action: "buy",
        type: "CE",
        strike,
        lots: 1,
        premium: live ? premiumAt(live, strike, "CE") : 0,
      },
    ]);
    setActivePreset(null);
  };

  const analysis = useMemo(
    () => (spot > 0 ? analyse(legs, lotSize, spot) : null),
    [legs, lotSize, spot],
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Options Strategy Builder"
        subtitle="Pick a preset or build multi-leg positions. Payoff is at expiry, priced off the live chain LTP."
      />

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-fg-faint">
          Underlying
          <select
            value={underlying}
            onChange={(e) => setUnderlying(e.target.value)}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg"
          >
            {(underlyings ?? [underlying]).map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-fg-faint">
          Expiry
          <select
            value={expiry}
            onChange={(e) => setExpiryPick(e.target.value)}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg"
          >
            {(expiries ?? []).map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-fg-faint">
          Lot size
          <input
            type="number"
            min={1}
            value={lotSize}
            onChange={(e) => setLotSizeOverride(Math.max(1, Number(e.target.value) || 1))}
            className="h-8 w-24 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg tabular-nums"
          />
        </label>
        {live && (
          <div className="ml-auto text-xs text-fg-muted">
            Spot <span className="font-semibold tabular-nums">{n(live.spot)}</span> · ATM{" "}
            <span className="font-semibold tabular-nums">{n(live.atm_strike, 0)}</span>
          </div>
        )}
      </div>

      {chain && !chain.available ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-fg-muted">{chain.reason}</CardContent>
        </Card>
      ) : !live ? (
        <p className="text-sm text-fg-faint">Loading chain…</p>
      ) : (
        <>
          <SectionCard title="Presets">
            <div className="flex flex-col gap-3">
              {PRESET_GROUPS.map((g) => (
                <div key={g.outlook} className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "w-16 text-xs font-semibold",
                      g.tone === "pos" ? "text-pos" : g.tone === "neg" ? "text-neg" : "text-fg-muted",
                    )}
                  >
                    {g.outlook}
                  </span>
                  {g.presets.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      title={p.hint}
                      onClick={() => applyPreset(p.key)}
                      className={cn(
                        "rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
                        activePreset === p.key
                          ? "border-accent bg-accent-soft text-accent"
                          : "border-line-strong text-fg-muted hover:text-fg",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard
            title="Legs"
            bodyClassName="p-0"
            actions={
              <button
                type="button"
                onClick={addLeg}
                className="flex items-center gap-1 rounded-md border border-line-strong px-2 py-1 text-xs text-fg-muted hover:text-fg"
              >
                <Plus className="h-3.5 w-3.5" /> Add leg
              </button>
            }
          >
            {legs.length === 0 ? (
              <p className="px-4 py-8 text-center text-xs text-fg-faint">
                Pick a preset above or add a leg to start.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] text-xs">
                  <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-wide text-fg-faint">
                      <th className="px-3 py-2 text-left">Action</th>
                      <th className="px-3 py-2 text-left">Type</th>
                      <th className="px-3 py-2 text-right">Strike</th>
                      <th className="px-3 py-2 text-right">Lots</th>
                      <th className="px-3 py-2 text-right">Premium</th>
                      <th className="px-3 py-2 text-right">Net ₹</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {legs.map((l) => {
                      const net =
                        (l.action === "buy" ? -1 : 1) * l.premium * l.lots * lotSize;
                      return (
                        <tr key={l.id} className="border-b border-line/60">
                          <td className="px-3 py-1.5">
                            <select
                              value={l.action}
                              onChange={(e) => updateLeg(l.id, { action: e.target.value as Action })}
                              className={cn(
                                "rounded border border-line-strong bg-surface px-1.5 py-1 font-medium",
                                l.action === "buy" ? "text-pos" : "text-neg",
                              )}
                            >
                              <option value="buy">Buy</option>
                              <option value="sell">Sell</option>
                            </select>
                          </td>
                          <td className="px-3 py-1.5">
                            <select
                              value={l.type}
                              onChange={(e) => updateLeg(l.id, { type: e.target.value as OptType })}
                              className="rounded border border-line-strong bg-surface px-1.5 py-1"
                            >
                              <option value="CE">CE</option>
                              <option value="PE">PE</option>
                            </select>
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <select
                              value={l.strike}
                              onChange={(e) => updateLeg(l.id, { strike: Number(e.target.value) })}
                              className="rounded border border-line-strong bg-surface px-1.5 py-1 tabular-nums"
                            >
                              {strikes.map((s) => (
                                <option key={s} value={s}>
                                  {s}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <input
                              type="number"
                              min={1}
                              value={l.lots}
                              onChange={(e) =>
                                updateLeg(l.id, { lots: Math.max(1, Number(e.target.value) || 1) })
                              }
                              className="w-14 rounded border border-line-strong bg-surface px-1.5 py-1 text-right tabular-nums"
                            />
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <input
                              type="number"
                              min={0}
                              step="0.05"
                              value={l.premium}
                              onChange={(e) =>
                                updateLeg(l.id, { premium: Math.max(0, Number(e.target.value) || 0) })
                              }
                              className="w-20 rounded border border-line-strong bg-surface px-1.5 py-1 text-right tabular-nums"
                            />
                          </td>
                          <td
                            className={cn(
                              "px-3 py-1.5 text-right tabular-nums",
                              net >= 0 ? "text-pos" : "text-neg",
                            )}
                          >
                            {rupee(net)}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <button
                              type="button"
                              onClick={() => setLegs((ls) => ls.filter((x) => x.id !== l.id))}
                              className="text-fg-faint hover:text-neg"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {analysis && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard
                  label={analysis.netPremium >= 0 ? "Net credit" : "Net debit"}
                  value={rupee(Math.abs(analysis.netPremium))}
                  deltaTone={analysis.netPremium >= 0 ? "pos" : "neg"}
                />
                <StatCard
                  label="Max profit"
                  value={analysis.maxProfit == null ? "Unlimited" : rupee(analysis.maxProfit)}
                  deltaTone="pos"
                />
                <StatCard
                  label="Max loss"
                  value={analysis.maxLoss == null ? "Unlimited" : rupee(analysis.maxLoss)}
                  deltaTone="neg"
                />
                <StatCard
                  label="Breakeven"
                  value={
                    analysis.breakevens.length
                      ? analysis.breakevens.map((b) => n(b, 0)).join(" / ")
                      : "–"
                  }
                />
              </div>

              <SectionCard title="Payoff at expiry">
                <div className="h-72 w-full">
                  <ResponsiveContainer>
                    <AreaChart data={analysis.curve} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                      <defs>
                        <linearGradient id="pnlPos" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--color-pos)" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="var(--color-pos)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line-strong)" />
                      <XAxis
                        dataKey="spot"
                        stroke="var(--color-fg-faint)"
                        fontSize={11}
                        tickFormatter={(v: number) => n(v, 0)}
                      />
                      <YAxis
                        stroke="var(--color-fg-faint)"
                        fontSize={11}
                        width={70}
                        tickFormatter={(v: number) => rupee(v)}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "var(--color-surface)",
                          border: "1px solid var(--color-line-strong)",
                          color: "var(--color-fg)",
                          fontSize: 12,
                        }}
                        formatter={(v): [string, string] => [rupee(Number(v)), "P&L"]}
                        labelFormatter={(v) => `Spot ${n(Number(v), 0)}`}
                      />
                      <ReferenceLine y={0} stroke="var(--color-fg-faint)" />
                      <ReferenceLine
                        x={analysis.curve.reduce((best, p) =>
                          Math.abs(p.spot - spot) < Math.abs(best.spot - spot) ? p : best,
                        ).spot}
                        stroke="var(--color-accent)"
                        strokeDasharray="4 3"
                        label={{ value: "Spot", position: "top", fill: "var(--color-accent)", fontSize: 10 }}
                      />
                      {analysis.breakevens.map((b) => (
                        <ReferenceLine
                          key={b}
                          x={analysis.curve.reduce((best, p) =>
                            Math.abs(p.spot - b) < Math.abs(best.spot - b) ? p : best,
                          ).spot}
                          stroke="var(--color-fg-faint)"
                          strokeDasharray="2 2"
                        />
                      ))}
                      <Area
                        type="monotone"
                        dataKey="pnl"
                        stroke="var(--color-accent)"
                        strokeWidth={2}
                        fill="url(#pnlPos)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-2 text-[11px] text-fg-faint">
                  Payoff assumes the position is held to expiry and each leg fills at the shown
                  premium. Brokerage, STT and slippage are not included.
                </p>
              </SectionCard>
            </>
          )}
        </>
      )}
    </div>
  );
}
