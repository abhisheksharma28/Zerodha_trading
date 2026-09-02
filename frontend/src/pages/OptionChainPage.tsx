import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { optionsApi } from "@/api/options";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent } from "@/components/ui/card";
import { useNow } from "@/hooks/useNow";
import { cn } from "@/lib/utils";

const RANGES = [10, 20, 40, 0] as const; // 0 = all
const n = (v: number | null | undefined, d = 2) =>
  v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: d });
const oi = (v: number | null | undefined) =>
  v == null ? "–" : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : `${v}`;

export default function OptionChainPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [underlying, setUnderlyingState] = useState(
    () => (searchParams.get("underlying") || "NIFTY").toUpperCase(),
  );
  const setUnderlying = (u: string) => {
    setUnderlyingState(u);
    setExpiryPick("");
    setSearchParams((prev) => {
      prev.set("underlying", u);
      return prev;
    });
  };
  const [expiryPick, setExpiryPick] = useState<string>("");
  const [range, setRange] = useState<(typeof RANGES)[number]>(20);
  const now = useNow(1000);

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
  const expiry =
    expiryPick && expiries?.includes(expiryPick) ? expiryPick : (expiries?.[0] ?? "");
  const setExpiry = setExpiryPick;

  const { data, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ["opt", "chain", underlying, expiry],
    queryFn: () => optionsApi.chain(underlying, expiry),
    enabled: !!expiry,
    refetchInterval: 3_000,
    refetchIntervalInBackground: false,
  });

  const rows = useMemo(() => {
    if (!data?.available) return [];
    if (!range || data.atm_strike == null) return data.rows;
    const atmIdx = data.rows.findIndex((r) => r.strike === data.atm_strike);
    if (atmIdx < 0) return data.rows;
    return data.rows.slice(Math.max(0, atmIdx - range), atmIdx + range + 1);
  }, [data, range]);

  const maxOi = useMemo(
    () =>
      Math.max(
        1,
        ...rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]),
      ),
    [rows],
  );

  const secs = dataUpdatedAt ? Math.max(0, Math.round((now - dataUpdatedAt) / 1000)) : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Option Chain"
        subtitle="Live NSE-style chain from the Zerodha instrument master + quotes. IV is back-solved from LTP."
        actions={
          <span className="text-xs text-fg-faint">
            {isFetching ? "updating…" : secs == null ? "" : secs <= 3 ? "live" : `${secs}s ago`}
          </span>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
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
        <select
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          className="h-8 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg"
        >
          {(expiries ?? []).map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
        <div className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium",
                r === range ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
              )}
            >
              {r === 0 ? "All" : `±${r}`}
            </button>
          ))}
        </div>
      </div>

      {data && !data.available ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-fg-muted">{data.reason}</CardContent>
        </Card>
      ) : !data ? (
        <p className="text-sm text-fg-faint">Loading chain…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label={`${underlying} spot`} value={n(data.spot)} />
            <StatCard label="ATM strike" value={n(data.atm_strike, 0)} />
            <StatCard
              label="PCR (OI)"
              value={n(data.pcr)}
              deltaTone={(data.pcr ?? 1) >= 1 ? "pos" : "neg"}
            />
            <StatCard label="Max pain" value={n(data.max_pain, 0)} />
          </div>

          <SectionCard title={`${underlying} · ${expiry}`} bodyClassName="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[52rem] text-xs tabular-nums">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-wide text-fg-faint">
                    <th className="px-2 py-2 text-right">Call OI</th>
                    <th className="px-2 py-2 text-right">Vol</th>
                    <th className="px-2 py-2 text-right">IV</th>
                    <th className="px-2 py-2 text-right">Call LTP</th>
                    <th className="px-2 py-2 text-center font-semibold text-fg-muted">Strike</th>
                    <th className="px-2 py-2 text-left">Put LTP</th>
                    <th className="px-2 py-2 text-left">IV</th>
                    <th className="px-2 py-2 text-left">Vol</th>
                    <th className="px-2 py-2 text-left">Put OI</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const atm = r.strike === data.atm_strike;
                    return (
                      <tr
                        key={r.strike}
                        className={cn(
                          "border-b border-line/60",
                          atm && "bg-accent-soft/60",
                        )}
                      >
                        <td className="relative px-2 py-1.5 text-right">
                          <span
                            className="absolute inset-y-0 right-0 bg-pos/10"
                            style={{ width: `${((r.call?.oi ?? 0) / maxOi) * 100}%` }}
                          />
                          <span className="relative">{oi(r.call?.oi)}</span>
                        </td>
                        <td className="px-2 py-1.5 text-right text-fg-muted">{oi(r.call?.volume)}</td>
                        <td className="px-2 py-1.5 text-right text-fg-muted">{n(r.call?.iv, 1)}</td>
                        <td className="px-2 py-1.5 text-right text-pos">{n(r.call?.ltp)}</td>
                        <td className="px-2 py-1.5 text-center font-semibold">{n(r.strike, 0)}</td>
                        <td className="px-2 py-1.5 text-left text-neg">{n(r.put?.ltp)}</td>
                        <td className="px-2 py-1.5 text-left text-fg-muted">{n(r.put?.iv, 1)}</td>
                        <td className="px-2 py-1.5 text-left text-fg-muted">{oi(r.put?.volume)}</td>
                        <td className="relative px-2 py-1.5 text-left">
                          <span
                            className="absolute inset-y-0 left-0 bg-neg/10"
                            style={{ width: `${((r.put?.oi ?? 0) / maxOi) * 100}%` }}
                          />
                          <span className="relative">{oi(r.put?.oi)}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>
          <p className="text-[11px] text-fg-faint">
            Total Call OI {oi(data.total_call_oi)} · Total Put OI {oi(data.total_put_oi)} · as of{" "}
            {new Date(data.as_of).toLocaleString()}
          </p>
        </>
      )}
    </div>
  );
}
