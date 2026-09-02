import type { OptionChain, OptionRow } from "@/api/options";
import type { LiveTick } from "@/lib/marketStream";

export type LiveChain = Extract<OptionChain, { available: true }>;

// Index -> spot instrument symbol for the live tick stream.
export const SPOT_SYMBOL: Record<string, string> = {
  NIFTY: "NSE:NIFTY 50",
  BANKNIFTY: "NSE:NIFTY BANK",
  FINNIFTY: "NSE:NIFTY FIN SERVICE",
  MIDCPNIFTY: "NSE:NIFTY MIDCAP SELECT",
  NIFTYNXT50: "NSE:NIFTY NEXT 50",
};

export function spotSymbolFor(underlying: string): string {
  return SPOT_SYMBOL[underlying] ?? `NSE:${underlying}`;
}

export function chainSubscriptions(chain: LiveChain, spotSym: string): string[] {
  const out = [spotSym];
  for (const r of chain.rows) {
    if (r.call?.tradingsymbol) out.push(`NFO:${r.call.tradingsymbol}`);
    if (r.put?.tradingsymbol) out.push(`NFO:${r.put.tradingsymbol}`);
  }
  return out;
}

// Fold live ticks into a REST chain: per-leg LTP / OI / volume, spot, and
// recomputed ATM / PCR / max-pain / totals. IV stays server-computed.
export function overlayChain(
  chain: LiveChain,
  ticks: Record<string, LiveTick>,
  spotSym: string,
): LiveChain {
  const legLive = (ts?: string) => (ts ? ticks[`NFO:${ts}`] : undefined);
  const rows: OptionRow[] = chain.rows.map((r) => {
    const c = legLive(r.call?.tradingsymbol);
    const p = legLive(r.put?.tradingsymbol);
    return {
      ...r,
      call: r.call
        ? { ...r.call, ltp: c?.ltp ?? r.call.ltp, oi: c?.oi ?? r.call.oi, volume: c?.volume ?? r.call.volume }
        : r.call,
      put: r.put
        ? { ...r.put, ltp: p?.ltp ?? r.put.ltp, oi: p?.oi ?? r.put.oi, volume: p?.volume ?? r.put.volume }
        : r.put,
    };
  });

  const spot = ticks[spotSym]?.ltp ?? chain.spot;
  const atm_strike =
    spot != null && rows.length
      ? rows.reduce(
          (best, r) => (Math.abs(r.strike - spot) < Math.abs(best - spot) ? r.strike : best),
          rows[0].strike,
        )
      : chain.atm_strike;

  const totCall = rows.reduce((s, r) => s + (r.call?.oi ?? 0), 0);
  const totPut = rows.reduce((s, r) => s + (r.put?.oi ?? 0), 0);
  const pain = (k: number) =>
    rows.reduce(
      (acc, r) =>
        acc +
        Math.max(0, k - r.strike) * (r.call?.oi ?? 0) +
        Math.max(0, r.strike - k) * (r.put?.oi ?? 0),
      0,
    );
  const max_pain = rows.length
    ? rows.reduce((best, r) => (pain(r.strike) < pain(best) ? r.strike : best), rows[0].strike)
    : chain.max_pain;

  return {
    ...chain,
    rows,
    spot,
    atm_strike,
    pcr: totCall ? Math.round((totPut / totCall) * 100) / 100 : chain.pcr,
    max_pain,
    total_call_oi: totCall,
    total_put_oi: totPut,
  };
}
