import { Link } from "react-router-dom";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import { useDeployments } from "@/hooks/useDeployments";
import { useStrategies } from "@/hooks/useStrategies";
import { useBacktests } from "@/hooks/useBacktests";
import { useBrokerStatus } from "@/hooks/useBroker";

export default function DashboardPage() {
  const strategies = useStrategies();
  const deployments = useDeployments();
  const backtests = useBacktests();
  const broker = useBrokerStatus();

  const running = deployments.data?.filter((d) => d.status === "running") ?? [];
  const live = running.filter((d) => d.mode === "live");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <p className="text-sm text-fg-muted">
          Overview of strategies, backtests, and deployments across every mode.
        </p>
      </div>

      {live.length > 0 && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="flex items-center justify-between py-3">
            <p className="text-sm font-medium text-red-400">
              {live.length} deployment{live.length > 1 ? "s" : ""} currently trading LIVE with real
              money.
            </p>
            <Link to="/monitoring" className="text-xs text-red-300 underline underline-offset-2">
              Go to monitoring
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Strategies" value={strategies.data?.length ?? "–"} />
        <StatCard label="Backtests" value={backtests.data?.length ?? "–"} />
        <StatCard label="Running deployments" value={running.length} />
        <StatCard
          label="Broker"
          value={broker.data?.connected ? "Connected" : "Not connected"}
          valueClassName={broker.data?.connected ? "text-emerald-400" : "text-fg-muted"}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Active deployments</CardTitle>
          <CardDescription>Deployments currently in RUNNING state, any mode.</CardDescription>
        </CardHeader>
        <CardContent>
          {running.length === 0 ? (
            <p className="text-sm text-fg-faint">No deployments are currently running.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {running.map((d) => (
                <li key={d.id}>
                  <Link
                    to={`/deployments/${d.id}`}
                    className="flex items-center justify-between rounded-md border border-line px-3 py-2 hover:bg-elevated/60"
                  >
                    <span className="text-sm">{d.name}</span>
                    <ModeBadge mode={d.mode} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string | number;
  valueClassName?: string;
}) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-xs uppercase tracking-wide text-fg-faint">{label}</p>
        <p className={`mt-1 text-2xl font-semibold ${valueClassName ?? ""}`}>{value}</p>
      </CardContent>
    </Card>
  );
}
