import { useMemo } from "react";

import { useSectorSeasonality } from "@/hooks/useLeaderboard";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// t-stat -> cell colour. Only positive, significant edges get warm colour.
function cellCls(t: number, edge: number): string {
  if (edge <= 0) return t <= -1.5 ? "bg-neg/15 text-neg" : "text-fg-faint";
  if (t >= 2.0) return "bg-pos/25 text-pos font-semibold";
  if (t >= 1.0) return "bg-pos/12 text-pos";
  if (t >= 0.4) return "bg-pos/[0.06] text-fg-muted";
  return "text-fg-faint";
}

export default function SeasonalityPage() {
  const { data, isLoading, isError } = useSectorSeasonality(10);

  const sectors = useMemo(
    () => (data ? [...data.sectors].sort() : []),
    [data],
  );
  const short = (s: string) => s.replace(/^NIFTY /, "");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Sector Seasonality</h1>
        <p className="mt-1 max-w-3xl text-sm text-fg-muted">
          Which NSE sector index has historically been strong in which calendar month, over the
          last {data?.years_covered ?? 10} years. The number is the <strong>seasonal edge</strong> —
          that month's return <em>minus that year's average month</em>, so a sector that merely had
          a good year does not look strong every month. <strong>t</strong> is the Student t-stat:
          |t| ≥ 1 is a real signal, ≥ 2 is strong. Method follows Gultekin &amp; Gultekin (1983) and
          Keloharju et&nbsp;al. (2021).
        </p>
      </div>

      {isLoading && <p className="py-10 text-center text-sm text-fg-faint">Building the table…</p>}
      {isError && (
        <p className="py-10 text-center text-sm text-neg">
          Could not load seasonality — the sector-index history pull may have failed.
        </p>
      )}

      {data && (
        <>
          {/* India calendar anchors */}
          <div className="rounded-lg border border-line bg-surface p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
              India calendar anchors
            </p>
            <div className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-muted">
              {Object.entries(data.india_calendar_anchors).map(([m, why]) => (
                <span key={m}>
                  <span className="font-semibold text-fg">{m}</span> — {why}
                </span>
              ))}
            </div>
          </div>

          {/* month -> top sectors */}
          <section>
            <h2 className="mb-2 text-sm font-semibold text-fg">Best sectors, month by month</h2>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {MONTHS.map((m) => {
                const rows = data.calendar_winners[m] ?? [];
                const anchor = data.india_calendar_anchors[m];
                return (
                  <div key={m} className="rounded-lg border border-line bg-surface p-3">
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm font-semibold text-fg">{m}</span>
                      {anchor && <span className="text-[10px] text-accent">{anchor}</span>}
                    </div>
                    {rows.length === 0 ? (
                      <p className="mt-1 text-[11px] text-fg-faint">No sector clears the filter.</p>
                    ) : (
                      <ul className="mt-1 space-y-0.5">
                        {rows.map((r) => (
                          <li key={r.sector} className="flex items-center justify-between text-xs">
                            <span className="text-fg-muted">{short(r.sector)}</span>
                            <span className="tabular-nums">
                              <span className={r.seasonal_edge_pct >= 0 ? "text-pos" : "text-neg"}>
                                {r.seasonal_edge_pct >= 0 ? "+" : ""}
                                {num(r.seasonal_edge_pct, 1)}%
                              </span>
                              <span className="ml-1.5 text-fg-faint">t{num(r.t_stat, 1)}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          {/* sector x month grid */}
          <section>
            <h2 className="mb-2 text-sm font-semibold text-fg">
              Full grid — seasonal edge % (shaded by t-stat)
            </h2>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[720px] text-xs tabular-nums">
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
                    const row = data.per_sector[sec] ?? {};
                    const sig = new Set(data.significant_months_per_sector[sec] ?? []);
                    return (
                      <tr key={sec} className="border-b border-line/60 last:border-0">
                        <td className="whitespace-nowrap px-2 py-1 text-left text-fg-muted">
                          {short(sec)}
                        </td>
                        {MONTHS.map((m) => {
                          const s = row[m];
                          if (!s) return <td key={m} className="px-1.5 py-1 text-right text-fg-faint">·</td>;
                          return (
                            <td
                              key={m}
                              className={cn(
                                "px-1.5 py-1 text-right",
                                cellCls(s.t_stat, s.mean_pct),
                                sig.has(m) && "ring-1 ring-inset ring-pos/40",
                              )}
                              title={`${sec} ${m}: edge ${num(s.mean_pct, 2)}% · t ${num(
                                s.t_stat,
                                2,
                              )} · hit ${Math.round(s.hit_rate * 100)}% · ${s.years}y · raw ${num(
                                s.raw_mean_pct,
                                2,
                              )}%`}
                            >
                              {s.mean_pct >= 0 ? "+" : ""}
                              {num(s.mean_pct, 1)}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-1.5 text-[10px] text-fg-faint">
              A green ring marks a month where the sector's edge is positive and t ≥ 1. Hover a cell
              for the raw (non-de-meaned) return, hit rate and sample size. This is the table the
              <span className="font-medium"> seasonal-sector-rotation</span> and
              <span className="font-medium"> seasonal-sector-stock-rotation</span> strategies trade
              on. Not investment advice; calendar edges decay as they become known.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
