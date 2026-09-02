import { useMemo } from "react";

import type { Capabilities } from "@/api/orderflow";
import { Sparkline } from "@/components/Sparkline";
import { DataQualityBadge } from "@/components/orderflow/DataQualityBadge";
import { VolumeProfilePanel } from "@/components/orderflow/VolumeProfilePanel";
import { countCompact, num } from "@/lib/format";
import { useEstimatedDelta, useOrderFlowCapabilities, useVolumeProfile } from "@/hooks/useOrderFlow";
import { cn } from "@/lib/utils";

function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          tone === "pos" && "text-pos",
          tone === "neg" && "text-neg",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function OrderFlowPanel({
  symbol,
  timeframe,
  days,
  lastPrice,
}: {
  symbol: string;
  timeframe: string;
  days?: number;
  lastPrice?: number | null;
}) {
  const caps = useOrderFlowCapabilities();
  const live = (caps.data?.live ?? undefined) as Capabilities | undefined;
  const historical = (caps.data?.historical ?? undefined) as Capabilities | undefined;

  // Volume profile from the same window the chart shows. 1-minute bars give
  // the finest honest resolution; fall back to the chart timeframe if the
  // window is very long (keeps the request bounded).
  const profileTf = days && days > 400 ? timeframe : "1m";
  const vp = useVolumeProfile(symbol, { timeframe: profileTf, days });
  const ed = useEstimatedDelta(symbol);

  const cvdSeries = useMemo(() => (ed.data?.series ?? []).map((b) => b.cvd), [ed.data]);
  const profile = vp.data?.available ? vp.data.profile : undefined;

  return (
    <div className="rounded-lg border border-line-strong bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold">Order Flow Analytics</span>
          <span className="text-xs text-fg-faint">
            {symbol} · profile {profile?.source_interval ?? profileTf}
          </span>
        </div>
        <DataQualityBadge live={live} historical={historical} />
      </div>

      <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Volume profile */}
        <div>
          {vp.isLoading ? (
            <p className="py-12 text-center text-sm text-fg-faint">Building volume profile…</p>
          ) : !profile ? (
            <p className="py-12 text-center text-sm text-fg-faint">
              {vp.data?.reason ?? "Volume profile unavailable."}
            </p>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1">
                <Stat label="POC" value={profile.poc_price != null ? num(profile.poc_price) : "—"} />
                <Stat label="VAH" value={profile.vah_price != null ? num(profile.vah_price) : "—"} />
                <Stat label="VAL" value={profile.val_price != null ? num(profile.val_price) : "—"} />
                <Stat label={`Value area ${Math.round(profile.value_area_pct * 100)}%`} value={`${countCompact(profile.total_volume * profile.value_area_pct)}`} />
                <Stat label="Bars" value={String(profile.bars_used)} />
                <Stat label="HVN / LVN" value={`${profile.hvn_prices.length} / ${profile.lvn_prices.length}`} />
              </div>
              <VolumeProfilePanel profile={profile} lastPrice={lastPrice} />
              <p className="mt-2 text-[11px] leading-relaxed text-fg-faint">
                {profile.method}
              </p>
            </>
          )}
        </div>

        {/* Estimated live delta / CVD */}
        <div className="rounded-md border border-line bg-elevated p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            <span className="text-xs font-semibold text-accent">ESTIMATED DELTA · live</span>
          </div>

          {!ed.data?.available ? (
            <p className="text-xs text-fg-faint">
              {ed.data?.reason ?? "Waiting for live snapshots…"} Delta/CVD only
              accrue while the market is open and this instrument is streaming.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                <Stat label="Bar buy" value={countCompact(ed.data.current_bar?.buy_volume)} tone="pos" />
                <Stat label="Bar sell" value={countCompact(ed.data.current_bar?.sell_volume)} tone="neg" />
                <Stat
                  label="Bar delta"
                  value={num(ed.data.current_bar?.delta ?? 0, 0)}
                  tone={(ed.data.current_bar?.delta ?? 0) >= 0 ? "pos" : "neg"}
                />
                <Stat
                  label="Session CVD"
                  value={num(ed.data.session_cvd ?? 0, 0)}
                  tone={(ed.data.session_cvd ?? 0) >= 0 ? "pos" : "neg"}
                />
              </div>
              <div className="mt-2 h-16">
                <Sparkline
                  data={cvdSeries.length > 1 ? cvdSeries : [0, 0]}
                  tone={(ed.data.session_cvd ?? 0) >= 0 ? "pos" : "neg"}
                />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-fg-faint">
                <span>
                  conf {ed.data.classification_confidence != null ? Math.round(ed.data.classification_confidence * 100) : "—"}%
                </span>
                <span>
                  {Object.entries(ed.data.classification_mix ?? {})
                    .map(([k, v]) => `${k.replace("_RULE", "").replace("CARRY_PREV", "carry").toLowerCase()} ${v}`)
                    .join(" · ")}
                </span>
              </div>
            </>
          )}

          <details className="mt-2">
            <summary className="cursor-pointer text-[10px] text-fg-faint">Why "estimated"?</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[10px] text-fg-faint">
              {(ed.data?.caveats ?? []).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </details>
        </div>
      </div>
    </div>
  );
}
