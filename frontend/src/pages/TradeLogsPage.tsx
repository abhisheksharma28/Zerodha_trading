import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import { ordersApi } from "@/api/orders";
import { useDeployments } from "@/hooks/useDeployments";

export default function TradeLogsPage() {
  const { data: deployments } = useDeployments();
  const [deploymentId, setDeploymentId] = useState("");

  const { data: orders, isLoading } = useQuery({
    queryKey: ["orders", "deployment", deploymentId],
    queryFn: () => ordersApi.byDeployment(deploymentId),
    enabled: !!deploymentId,
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Trade Logs</h1>
        <p className="text-sm text-fg-muted">
          Every order across every mode lives in one unified log — select a deployment to inspect
          its orders.
        </p>
      </div>

      <select
        value={deploymentId}
        onChange={(e) => setDeploymentId(e.target.value)}
        className="h-9 max-w-sm rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
      >
        <option value="">Select a deployment…</option>
        {deployments?.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} ({d.mode})
          </option>
        ))}
      </select>

      <Card>
        <CardHeader>
          <CardTitle>Orders</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <p className="text-sm text-fg-faint">Loading…</p>}
          {!deploymentId && (
            <p className="text-sm text-fg-faint">Select a deployment above to view its orders.</p>
          )}
          {orders && orders.length === 0 && (
            <p className="text-sm text-fg-faint">No orders for this deployment yet.</p>
          )}
          {orders && orders.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-fg-faint">
                  <tr>
                    <th className="py-2 pr-4">Mode</th>
                    <th className="py-2 pr-4">Symbol</th>
                    <th className="py-2 pr-4">Side</th>
                    <th className="py-2 pr-4">Qty</th>
                    <th className="py-2 pr-4">Price</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Broker order ID</th>
                    <th className="py-2 pr-4">Placed</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.id} className="border-t border-line">
                      <td className="py-2 pr-4">
                        <ModeBadge mode={o.mode} />
                      </td>
                      <td className="py-2 pr-4">{o.tradingsymbol}</td>
                      <td className={`py-2 pr-4 ${o.transaction_type === "BUY" ? "text-emerald-400" : "text-red-400"}`}>
                        {o.transaction_type}
                      </td>
                      <td className="py-2 pr-4">{o.quantity}</td>
                      <td className="py-2 pr-4">{o.price ?? "market"}</td>
                      <td className="py-2 pr-4">{o.status}</td>
                      <td className="py-2 pr-4 text-fg-faint">{o.broker_order_id ?? "—"}</td>
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
