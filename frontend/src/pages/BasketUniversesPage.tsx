import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { useBasketUniverses, useUniverseScreen } from "@/hooks/useBaskets";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function BasketUniversesPage() {
  const nav = useNavigate();
  const { data: universes, isLoading } = useBasketUniverses();
  const [selected, setSelected] = useState<string | null>(null);
  const screen = useUniverseScreen(selected ?? undefined);

  return (
    <div className="flex flex-col gap-5">
      <button
        onClick={() => nav("/baskets")}
        className="flex w-fit items-center gap-1 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All baskets
      </button>

      <PageHeader
        title="Basket universes"
        subtitle="The named instrument pools the catalog products draw from. The eligibility screen checks each member against live data — enough history, no stale feed or gaps, above the penny-price floor — so 'listed here' becomes 'tradeable right now'."
      />

      <SectionCard title="Pools" index={1}>
        {isLoading || !universes ? (
          <p className="p-4 text-sm text-fg-faint">Loading…</p>
        ) : (
          <div className="divide-y divide-line">
            {universes.map((u) => (
              <button
                key={u.name}
                onClick={() => setSelected(selected === u.name ? null : u.name)}
                className={cn(
                  "flex w-full flex-col gap-0.5 px-4 py-2.5 text-left transition-colors hover:bg-elevated",
                  selected === u.name && "bg-elevated",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-fg">{u.label}</span>
                  <span className="text-[10px] uppercase tracking-wide text-fg-faint">{u.name}</span>
                  <span className="ml-auto text-xs tabular-nums text-fg-muted">
                    {u.n_members} names
                  </span>
                </div>
                <span className="text-xs text-fg-muted">{u.intent}</span>
                <span className="text-[11px] text-fg-faint">{u.curation}</span>
              </button>
            ))}
          </div>
        )}
      </SectionCard>

      {selected && (
        <SectionCard title={`Eligibility — ${selected}`} index={2}>
          <div className="flex flex-col gap-3 p-4">
            {screen.isLoading || !screen.data ? (
              <p className="text-sm text-fg-faint">Screening against live candles…</p>
            ) : (
              <>
                <p className="text-xs text-fg-faint">
                  As of {screen.data.as_of} · {screen.data.n_eligible}/{screen.data.n_members}{" "}
                  eligible · gate: ≥{screen.data.gate.min_history_bars} bars, ≤
                  {screen.data.gate.max_staleness_days}d stale, price ≥{" "}
                  {num(screen.data.gate.price_floor, 0)}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {screen.data.eligible.map((s) => (
                    <span
                      key={s}
                      className="rounded bg-pos/10 px-1.5 py-0.5 text-[11px] text-pos"
                    >
                      {s}
                    </span>
                  ))}
                </div>
                {screen.data.ineligible.length > 0 && (
                  <div className="overflow-x-auto rounded-md border border-line">
                    <table className="w-full min-w-[420px] text-xs">
                      <thead>
                        <tr className="border-b border-line bg-surface text-fg-faint">
                          <th className="px-2 py-1.5 text-left">Symbol</th>
                          <th className="px-2 py-1.5 text-left">Why it fails</th>
                        </tr>
                      </thead>
                      <tbody>
                        {screen.data.ineligible.map((m) => (
                          <tr key={m.symbol} className="border-b border-line/60 last:border-0">
                            <td className="px-2 py-1 text-left font-medium text-fg">{m.symbol}</td>
                            <td className="px-2 py-1 text-left text-neg">
                              {m.reasons.join("; ")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </SectionCard>
      )}
    </div>
  );
}
