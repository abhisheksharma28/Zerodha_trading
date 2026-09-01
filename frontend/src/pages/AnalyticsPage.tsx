import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { useBacktests } from "@/hooks/useBacktests";

export default function AnalyticsPage() {
  const { data: backtests } = useBacktests();
  const done = (backtests ?? []).filter((b) => b.status === "completed" && b.metrics);

  const avg = (key: string) => {
    const xs = done.map((b) => b.metrics?.[key]).filter((v): v is number => typeof v === "number");
    return xs.length ? xs.reduce((a, c) => a + c, 0) / xs.length : null;
  };
  const f = (v: number | null, d = 2) => (v == null ? "–" : v.toFixed(d));

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Analytics"
        subtitle="Aggregate performance across your completed backtests."
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Completed backtests" value={done.length} />
        <StatCard label="Avg return" value={`${f(avg("total_return_pct"))}%`} />
        <StatCard label="Avg Sharpe" value={f(avg("sharpe_ratio"))} />
        <StatCard label="Avg max drawdown" value={`${f(avg("max_drawdown_pct"))}%`} deltaTone="neg" />
      </div>

      <SectionCard title="Coming in the analytics phase">
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-fg-muted">
          <li>Year-by-year and monthly return breakdowns across strategies</li>
          <li>Rolling Sharpe / CAGR / drawdown and drawdown-duration curves</li>
          <li>Regime analysis (bull / bear / sideways / high-low volatility)</li>
          <li>Long vs short attribution and turnover / cost sensitivity</li>
        </ul>
        <p className="mt-3 text-xs text-fg-faint">
          These are computed from real backtest and deployment data — nothing is fabricated.{" "}
          <Link to="/backtests" className="text-accent hover:underline">
            Run more backtests
          </Link>{" "}
          to populate them.
        </p>
      </SectionCard>
    </div>
  );
}
