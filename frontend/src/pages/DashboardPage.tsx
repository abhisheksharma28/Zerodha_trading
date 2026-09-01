import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FlaskConical, LayoutGrid, Rocket, Wallet } from "lucide-react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import { useBacktests } from "@/hooks/useBacktests";
import { useBrokerStatus } from "@/hooks/useBroker";
import { useDeployments } from "@/hooks/useDeployments";
import { useStrategies } from "@/hooks/useStrategies";
import type { Backtest } from "@/types/api";

const TIP = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-line-strong)",
  color: "var(--color-fg)",
  fontSize: 12,
};

// Placeholder allocation — clearly labelled as sample, never presented as live.
const SAMPLE_ALLOCATION = [
  { name: "Equity", value: 52, color: "var(--color-accent)" },
  { name: "Options", value: 23, color: "#22b8cf" },
  { name: "Futures", value: 18, color: "#ffa94d" },
  { name: "Cash", value: 7, color: "var(--color-line-strong)" },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const strategies = useStrategies();
  const deployments = useDeployments();
  const backtests = useBacktests();
  const broker = useBrokerStatus();

  const running = deployments.data?.filter((d) => d.status === "running") ?? [];
  const live = running.filter((d) => d.mode === "live");

  const completed = (backtests.data ?? []).filter((b) => b.equity_curve && b.equity_curve.length > 1);
  const latest = completed.sort(
    (a, b) => +new Date(b.created_at) - +new Date(a.created_at),
  )[0];
  const equity =
    latest?.equity_curve?.map(([ts, v], i) => ({ i, ts, v: Number(v) })) ?? [];

  const recent = (backtests.data ?? [])
    .slice()
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    .slice(0, 6);

  const backtestCols: Column<Backtest>[] = [
    {
      key: "sym",
      header: "Universe",
      cell: (b) => (
        <span className="font-medium text-fg">{b.instrument_universe.join(", ")}</span>
      ),
    },
    { key: "tf", header: "TF", cell: (b) => b.timeframe },
    {
      key: "ret",
      header: "Return",
      align: "right",
      cell: (b) => {
        const r = b.metrics?.total_return_pct;
        if (r == null) return <span className="text-fg-faint">–</span>;
        return <span className={r < 0 ? "text-neg" : "text-pos"}>{r.toFixed(2)}%</span>;
      },
    },
    {
      key: "status",
      header: "Status",
      align: "right",
      cell: (b) => (
        <Badge
          variant={
            b.status === "completed"
              ? "success"
              : b.status === "failed"
                ? "destructive"
                : b.status === "running"
                  ? "info"
                  : "default"
          }
        >
          {b.status}
        </Badge>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Dashboard"
        subtitle="Strategies, backtests and deployments across every mode."
      />

      {live.length > 0 && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="flex items-center justify-between py-3">
            <p className="text-sm font-medium text-neg">
              {live.length} deployment{live.length > 1 ? "s" : ""} trading LIVE with real money.
            </p>
            <Link to="/monitoring" className="text-xs text-red-300 underline underline-offset-2">
              Go to monitoring →
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Strategies"
          value={strategies.data?.length ?? "–"}
          icon={LayoutGrid}
        />
        <StatCard label="Backtests Run" value={backtests.data?.length ?? "–"} icon={FlaskConical} />
        <StatCard label="Live Strategies" value={live.length} icon={Rocket} />
        <StatCard
          label="Total P&L"
          value={broker.data?.connected ? "—" : "Connect broker"}
          icon={Wallet}
          valueClassName={broker.data?.connected ? "" : "text-fg-muted text-base"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title="Portfolio Equity Curve"
          className="lg:col-span-2"
          actions={
            latest ? (
              <Link
                to={`/backtests/${latest.id}`}
                className="text-xs text-accent hover:underline"
              >
                {latest.instrument_universe.join(", ")} · {latest.timeframe}
              </Link>
            ) : null
          }
        >
          {equity.length === 0 ? (
            <p className="py-10 text-center text-sm text-fg-faint">
              Run a backtest to see an equity curve here.
            </p>
          ) : (
            <div className="h-56 w-full">
              <ResponsiveContainer>
                <AreaChart data={equity} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="i" stroke="var(--color-fg-faint)" fontSize={11} tickLine={false} />
                  <YAxis
                    stroke="var(--color-fg-faint)"
                    fontSize={11}
                    tickLine={false}
                    width={64}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip
                    contentStyle={TIP}
                    labelFormatter={(_, p) => p?.[0]?.payload?.ts ?? ""}
                  />
                  <Area
                    type="monotone"
                    dataKey="v"
                    stroke="var(--color-accent)"
                    strokeWidth={2}
                    fill="url(#eqfill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="Allocation"
          actions={<span className="text-[10px] uppercase text-fg-faint">Sample</span>}
        >
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={SAMPLE_ALLOCATION}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={45}
                  outerRadius={72}
                  paddingAngle={2}
                  stroke="none"
                >
                  {SAMPLE_ALLOCATION.map((s) => (
                    <Cell key={s.name} fill={s.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={TIP} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-fg-muted">
            {SAMPLE_ALLOCATION.map((s) => (
              <span key={s.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.name} {s.value}%
              </span>
            ))}
          </div>
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title="Recent Backtests"
          className="lg:col-span-2"
          actions={
            <Link to="/backtests" className="text-xs text-accent hover:underline">
              View all
            </Link>
          }
          bodyClassName="p-0"
        >
          <DataTable
            columns={backtestCols}
            rows={recent}
            rowKey={(b) => b.id}
            onRowClick={(b) => navigate(`/backtests/${b.id}`)}
            empty="No backtests yet."
          />
        </SectionCard>

        <SectionCard title="Active Deployments">
          {running.length === 0 ? (
            <p className="py-6 text-center text-sm text-fg-faint">Nothing running.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {running.map((d) => (
                <li key={d.id}>
                  <Link
                    to={`/deployments/${d.id}`}
                    className="flex items-center justify-between rounded-md border border-line px-3 py-2 hover:bg-elevated/60"
                  >
                    <span className="truncate text-sm">{d.name}</span>
                    <ModeBadge mode={d.mode} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
