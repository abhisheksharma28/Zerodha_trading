import { useNavigate } from "react-router-dom";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { useBacktests } from "@/hooks/useBacktests";
import type { Backtest } from "@/types/api";

export default function ReportsPage() {
  const navigate = useNavigate();
  const { data: backtests } = useBacktests();
  const rows = (backtests ?? [])
    .filter((b) => b.status === "completed")
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));

  const cols: Column<Backtest>[] = [
    {
      key: "name",
      header: "Report",
      cell: (b) => (
        <span className="font-medium text-fg">
          {b.instrument_universe.join(", ")} · {b.timeframe}
        </span>
      ),
    },
    {
      key: "date",
      header: "Generated",
      cell: (b) => new Date(b.created_at).toLocaleDateString(),
    },
    {
      key: "ret",
      header: "Net return",
      align: "right",
      cell: (b) => {
        const r = b.metrics?.total_return_pct;
        return r == null ? "–" : <span className={r < 0 ? "text-neg" : "text-pos"}>{r.toFixed(2)}%</span>;
      },
    },
    {
      key: "sharpe",
      header: "Sharpe",
      align: "right",
      cell: (b) => (b.metrics?.sharpe_ratio ?? "–") as number | string,
    },
    { key: "open", header: "", align: "right", cell: () => <Badge>Open</Badge> },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Reports"
        subtitle="Every completed backtest is a report — open one for the full institutional breakdown."
      />
      <SectionCard title="Backtest Reports" bodyClassName="p-0">
        <DataTable
          columns={cols}
          rows={rows}
          rowKey={(b) => b.id}
          onRowClick={(b) => navigate(`/backtests/${b.id}`)}
          empty="No completed backtests yet."
        />
      </SectionCard>
    </div>
  );
}
