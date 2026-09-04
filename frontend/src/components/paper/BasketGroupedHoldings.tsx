import { useQueries } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { basketsApi } from "@/api/baskets";
import type { PaperHolding } from "@/api/paperAccount";
import { DataTable, type Column } from "@/components/DataTable";
import { SectionCard } from "@/components/SectionCard";
import { useBaskets } from "@/hooks/useBaskets";
import { inr, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Holdings grouped by the basket that bought them, with a "Direct" bucket
 *  for everything held outside a basket. Falls back to a flat table when
 *  no basket is deployed. */
export function BasketGroupedHoldings({
  holdings,
  columns,
}: {
  holdings: PaperHolding[];
  columns: Column<PaperHolding>[];
}) {
  const nav = useNavigate();
  const { data: baskets = [] } = useBaskets();
  const deployed = baskets.filter((b) => b.status === "deployed");

  const statuses = useQueries({
    queries: deployed.map((b) => ({
      queryKey: ["baskets", b.id, "status"],
      queryFn: () => basketsApi.status(b.id),
      refetchInterval: 15_000,
    })),
  });

  if (deployed.length === 0) {
    return (
      <SectionCard title="Holdings" bodyClassName="p-0">
        <DataTable
          columns={columns}
          rows={holdings}
          rowKey={(h) => h.id}
          searchable
          searchPlaceholder="Filter holdings…"
          empty="No holdings. Buy a stock with product CNC to build your portfolio."
        />
      </SectionCard>
    );
  }

  const groups = deployed.map((b, i) => ({
    basket: b,
    status: statuses[i]?.data,
    symbols: new Set((statuses[i]?.data?.holdings ?? []).map((h) => h.symbol)),
  }));
  const inAnyBasket = new Set<string>();
  groups.forEach((g) => g.symbols.forEach((s) => inAnyBasket.add(s)));
  const direct = holdings.filter((h) => !inAnyBasket.has(h.tradingsymbol));

  return (
    <div className="flex flex-col gap-4">
      {groups.map(({ basket, status, symbols }) => (
        <SectionCard
          key={basket.id}
          title={
            <button className="hover:underline" onClick={() => nav(`/baskets/${basket.id}`)}>
              🧺 {basket.name}
            </button>
          }
          bodyClassName="p-0"
          actions={
            status ? (
              <span className="flex items-center gap-3 text-xs tabular-nums">
                <span className="text-fg-faint">
                  value <b className="text-fg">{inr(status.portfolio_value)}</b>
                </span>
                <span
                  className={cn(
                    "font-semibold",
                    (status.return_pct ?? 0) < 0 ? "text-neg" : "text-pos",
                  )}
                >
                  {pctSigned(status.return_pct ?? null, 2)}
                </span>
                {status.rebalance_due && (
                  <span className="rounded bg-amber-400/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-500">
                    rebalance due
                  </span>
                )}
              </span>
            ) : null
          }
        >
          <DataTable
            columns={columns}
            rows={holdings.filter((h) => symbols.has(h.tradingsymbol))}
            rowKey={(h) => h.id}
            empty="No filled holdings for this basket yet — check the order book."
          />
        </SectionCard>
      ))}

      <SectionCard title="Direct holdings (not in a basket)" bodyClassName="p-0">
        <DataTable
          columns={columns}
          rows={direct}
          rowKey={(h) => h.id}
          searchable
          searchPlaceholder="Filter…"
          empty="Everything you hold is inside a basket."
        />
      </SectionCard>
    </div>
  );
}
