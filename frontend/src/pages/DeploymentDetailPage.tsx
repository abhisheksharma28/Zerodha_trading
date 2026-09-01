import { useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import {
  useDeployDeployment,
  useDeployment,
  usePauseDeployment,
  useResumeDeployment,
  useStopDeployment,
} from "@/hooks/useDeployments";
import { useQuery } from "@tanstack/react-query";
import { ordersApi } from "@/api/orders";

export default function DeploymentDetailPage() {
  const { deploymentId } = useParams<{ deploymentId: string }>();
  const { data: deployment, isLoading } = useDeployment(deploymentId);
  const { data: orders } = useQuery({
    queryKey: ["orders", "deployment", deploymentId],
    queryFn: () => ordersApi.byDeployment(deploymentId as string),
    enabled: !!deploymentId,
    refetchInterval: 10_000,
  });

  const deploy = useDeployDeployment();
  const pause = usePauseDeployment();
  const resume = useResumeDeployment();
  const stop = useStopDeployment();

  if (isLoading) return <p className="text-sm text-fg-faint">Loading…</p>;
  if (!deployment) return <p className="text-sm text-fg-faint">Deployment not found.</p>;

  const isLive = deployment.mode === "live";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{deployment.name}</h1>
          <p className="text-sm text-fg-muted">{deployment.instrument_universe.join(", ")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge>{deployment.status}</Badge>
          <ModeBadge mode={deployment.mode} />
        </div>
      </div>

      {isLive && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="py-3 text-sm text-red-400">
            LIVE deployment — confirmed{" "}
            {deployment.live_trading_confirmed_at
              ? new Date(deployment.live_trading_confirmed_at).toLocaleString()
              : "—"}
            . Every order this deployment places is re-checked against this row at the moment of
            placement (app.execution.guard) — pausing or stopping here takes effect immediately.
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Controls</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          {(deployment.status === "pending" || deployment.status === "stopped") && (
            <Button onClick={() => deploy.mutate(deployment.id)} disabled={deploy.isPending}>
              Deploy
            </Button>
          )}
          {deployment.status === "running" && (
            <Button variant="secondary" onClick={() => pause.mutate(deployment.id)} disabled={pause.isPending}>
              Pause
            </Button>
          )}
          {deployment.status === "paused" && (
            <Button onClick={() => resume.mutate(deployment.id)} disabled={resume.isPending}>
              Resume
            </Button>
          )}
          {(deployment.status === "running" || deployment.status === "paused") && (
            <Button variant="destructive" onClick={() => stop.mutate(deployment.id)} disabled={stop.isPending}>
              Stop
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Orders</CardTitle>
        </CardHeader>
        <CardContent>
          {!orders || orders.length === 0 ? (
            <p className="text-sm text-fg-faint">No orders yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-fg-faint">
                  <tr>
                    <th className="py-2 pr-4">Symbol</th>
                    <th className="py-2 pr-4">Side</th>
                    <th className="py-2 pr-4">Qty</th>
                    <th className="py-2 pr-4">Price</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Placed</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.id} className="border-t border-line">
                      <td className="py-2 pr-4">{o.tradingsymbol}</td>
                      <td className={`py-2 pr-4 ${o.transaction_type === "BUY" ? "text-emerald-400" : "text-red-400"}`}>
                        {o.transaction_type}
                      </td>
                      <td className="py-2 pr-4">{o.quantity}</td>
                      <td className="py-2 pr-4">{o.price ?? "market"}</td>
                      <td className="py-2 pr-4">{o.status}</td>
                      <td className="py-2 pr-4 text-fg-faint">
                        {o.placed_at ? new Date(o.placed_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
