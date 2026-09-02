import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";

import { monitoringApi } from "@/api/monitoring";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ModeBadge } from "@/components/ModeBadge";
import { useDeployments } from "@/hooks/useDeployments";
import { inr } from "@/lib/format";

function CircuitBreakerRow() {
  const qc = useQueryClient();
  const { data: cb } = useQuery({
    queryKey: ["monitoring", "circuit-breakers"],
    queryFn: monitoringApi.circuitBreakers,
    refetchInterval: 3_000,
  });
  const override = useMutation({
    mutationFn: monitoringApi.overrideBreakers,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["monitoring", "circuit-breakers"] }),
  });
  if (!cb) return null;
  return (
    <div
      className={`flex items-center justify-between rounded-md border px-2.5 py-1.5 ${
        cb.halted ? "border-red-500/50 bg-red-500/5 text-neg" : "border-line text-fg-muted"
      }`}
    >
      <span>
        {cb.halted
          ? `AUTO-HALT: ${cb.reasons.map((r) => r.reason).join(", ")}`
          : cb.override_active
            ? "Auto-halt overridden by operator"
            : "Circuit breakers armed · no auto-halt"}
      </span>
      {cb.halted && (
        <button
          type="button"
          disabled={override.isPending}
          onClick={() => override.mutate()}
          className="rounded bg-fg-faint/20 px-2 py-1 text-[11px] font-medium hover:bg-fg-faint/30"
        >
          Override & resume
        </button>
      )}
    </div>
  );
}

function FlattenButton() {
  const qc = useQueryClient();
  const flatten = useMutation({
    mutationFn: monitoringApi.flatten,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitoring", "risk"] });
      qc.invalidateQueries({ queryKey: ["monitoring", "oms"] });
    },
  });
  return (
    <div className="mt-1">
      <button
        type="button"
        disabled={flatten.isPending}
        onClick={() => {
          if (
            window.confirm(
              "EMERGENCY FLATTEN: market-close every open LIVE position and engage the kill switch. Continue?",
            )
          )
            flatten.mutate();
        }}
        className="w-full rounded-md border border-red-500/60 bg-red-500/10 py-1.5 text-xs font-bold text-neg hover:bg-red-500/20"
      >
        {flatten.isPending ? "Flattening…" : "EMERGENCY FLATTEN ALL POSITIONS"}
      </button>
      {flatten.isError && (
        <p className="mt-1 text-[11px] text-neg">{(flatten.error as Error).message}</p>
      )}
      {flatten.isSuccess && (
        <p className="mt-1 text-[11px] text-fg-muted">
          {flatten.data.positions_flattened.length} leg(s) sent · kill switch engaged.
        </p>
      )}
    </div>
  );
}

function KillSwitchCard() {
  const qc = useQueryClient();
  const { data: risk } = useQuery({
    queryKey: ["monitoring", "risk"],
    queryFn: monitoringApi.risk,
    refetchInterval: 3_000,
  });
  const toggle = useMutation({
    mutationFn: (engaged: boolean) => monitoringApi.killSwitch("all", engaged),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["monitoring", "risk"] }),
  });

  const killed = risk?.global_kill ?? false;
  const deps = Object.entries(risk?.deployments ?? {});

  return (
    <Card className={killed ? "border-red-500/50 bg-red-500/5" : undefined}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            {killed ? (
              <ShieldAlert className="h-4 w-4 text-neg" />
            ) : (
              <ShieldCheck className="h-4 w-4 text-pos" />
            )}
            Risk & kill switch
          </CardTitle>
          <button
            type="button"
            disabled={toggle.isPending}
            onClick={() => toggle.mutate(!killed)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              killed
                ? "bg-pos text-white hover:bg-pos/90"
                : "bg-neg text-white hover:bg-neg/90"
            }`}
          >
            {killed ? "Release kill switch" : "ENGAGE KILL SWITCH"}
          </button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        <p className={killed ? "font-medium text-neg" : "text-fg-muted"}>
          {killed
            ? "All new orders are BLOCKED across every deployment. Open positions are untouched."
            : "Normal pre-trade risk checks active. Engaging stops all new orders instantly."}
        </p>

        <CircuitBreakerRow />
        <FlattenButton />
        {deps.length === 0 ? (
          <p className="text-fg-faint">No deployment risk activity yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full tabular-nums">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-fg-faint">
                  <th className="py-1 text-left font-medium">Deployment</th>
                  <th className="py-1 text-right font-medium">Orders (today / 1m)</th>
                  <th className="py-1 text-right font-medium">Realized P&L</th>
                  <th className="py-1 text-right font-medium">Positions</th>
                  <th className="py-1 text-right font-medium">Last reject</th>
                </tr>
              </thead>
              <tbody>
                {deps.map(([id, r]) => (
                  <tr key={id} className="border-t border-line">
                    <td className="py-1 text-left text-fg-muted">
                      {id.slice(0, 8)}
                      {r.killed && <span className="ml-1 text-neg">· killed</span>}
                    </td>
                    <td className="py-1 text-right">
                      {r.orders_today} / {r.orders_last_minute}
                    </td>
                    <td
                      className={`py-1 text-right ${
                        r.day_realized_pnl < 0 ? "text-neg" : "text-pos"
                      }`}
                    >
                      {inr(r.day_realized_pnl)}
                    </td>
                    <td className="py-1 text-right text-fg-faint">
                      {Object.keys(r.open_positions).length}
                    </td>
                    <td className="max-w-[12rem] truncate py-1 text-right text-fg-faint">
                      {r.last_reject ?? "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const OMS_STATE_TONE: Record<string, string> = {
  FILLED: "text-pos",
  PARTIALLY_FILLED: "text-accent",
  REJECTED: "text-neg",
  FAILED: "text-neg",
  CANCELLED: "text-fg-faint",
};

function OmsCard() {
  const { data: oms } = useQuery({
    queryKey: ["monitoring", "oms"],
    queryFn: monitoringApi.oms,
    refetchInterval: 3_000,
  });
  const orders = oms?.orders ?? [];
  if (orders.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Order management ({oms?.open ?? 0} open)</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-fg-faint">
          {Object.entries(oms?.counts ?? {}).map(([s, n]) => (
            <span key={s} className={OMS_STATE_TONE[s] ?? ""}>
              {s} {n}
            </span>
          ))}
        </p>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-surface text-[10px] uppercase tracking-wide text-fg-faint">
              <tr>
                <th className="py-1 pr-3 text-left">Symbol</th>
                <th className="py-1 pr-3 text-left">Side</th>
                <th className="py-1 pr-3 text-right">Qty / filled</th>
                <th className="py-1 pr-3 text-left">State</th>
                <th className="py-1 pr-3 text-right">Submit→fill</th>
                <th className="py-1 text-left">Broker id</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.internal_id} className="border-t border-line">
                  <td className="py-1 pr-3 text-left text-fg-muted">{o.tradingsymbol}</td>
                  <td className="py-1 pr-3 text-left">{o.side}</td>
                  <td className="py-1 pr-3 text-right">
                    {o.quantity}
                    {o.filled_qty > 0 && ` / ${o.filled_qty}`}
                  </td>
                  <td className={`py-1 pr-3 text-left font-medium ${OMS_STATE_TONE[o.state] ?? "text-fg-muted"}`}>
                    {o.state}
                    {o.reject_reason && (
                      <span className="block max-w-[14rem] truncate text-[10px] text-fg-faint">
                        {o.reject_reason}
                      </span>
                    )}
                  </td>
                  <td className="py-1 pr-3 text-right text-fg-faint">
                    {o.latency_ms.submit_to_fill != null ? `${o.latency_ms.submit_to_fill} ms` : "–"}
                  </td>
                  <td className="py-1 text-left text-fg-faint">{o.broker_order_id ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

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

      <KillSwitchCard />
      <OmsCard />

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
