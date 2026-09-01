import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import { useDeployments } from "@/hooks/useDeployments";

export default function MonitoringPage() {
  const { data: deployments, isLoading } = useDeployments();
  const running = deployments?.filter((d) => d.status === "running") ?? [];
  const attention = deployments?.filter((d) => d.status === "error") ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Monitoring</h1>
        <p className="text-sm text-fg-muted">
          Live view of every running deployment, refreshed every 10 seconds.
        </p>
      </div>

      {isLoading && <p className="text-sm text-fg-faint">Loading…</p>}

      {attention.length > 0 && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardHeader>
            <CardTitle className="text-neg">Needs attention</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {attention.map((d) => (
              <Link key={d.id} to={`/deployments/${d.id}`} className="text-sm text-red-300 underline">
                {d.name} — {d.error_message ?? "error"}
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {running.map((d) => (
          <Link key={d.id} to={`/deployments/${d.id}`}>
            <Card className="h-full hover:border-line-strong">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{d.name}</CardTitle>
                  <ModeBadge mode={d.mode} />
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <p className="text-xs text-fg-faint">{d.instrument_universe.join(", ")}</p>
                <div className="flex items-center justify-between text-xs text-fg-faint">
                  <span>
                    Deployed {d.deployed_at ? new Date(d.deployed_at).toLocaleString() : "—"}
                  </span>
                  <Badge variant="success">running</Badge>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
        {running.length === 0 && !isLoading && (
          <p className="text-sm text-fg-faint">No deployments are currently running.</p>
        )}
      </div>
    </div>
  );
}
