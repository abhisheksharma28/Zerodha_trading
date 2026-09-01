import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useCreateOptionsInstance,
  useEnterOptionsInstance,
  useEvaluateOptionsInstance,
  useExitOptionsInstance,
  useOptionsInstances,
  useOptionsTemplate,
} from "@/hooks/useOptionsStrategies";
import type { OptionsInstance } from "@/types/api";

const fmt = (v: number | null | undefined, d = 2) =>
  v == null ? "–" : v.toLocaleString(undefined, { maximumFractionDigits: d });

const ACTIVE_STATUSES = ["CREATED", "VALIDATING", "ENTRY_PENDING", "ENTERED", "ACTIVE"];

export default function OptionsHniPage() {
  const { data: template } = useOptionsTemplate();
  const { data: instances } = useOptionsInstances();
  const create = useCreateOptionsInstance();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{template?.name ?? "NIFTY Monthly HNI Strategy"}</h1>
          <p className="max-w-2xl text-sm text-fg-muted">
            {template?.structure} — Friday entry at 15:16 IST when the monthly expiry is 39–43 DTE.
            Exits on ±target/stop of deployed capital, the short strike being crossed while down more
            than the stop, a max holding period, or a pre-expiry safety exit.
          </p>
        </div>
        <Button
          onClick={() => create.mutate({ mode: "paper", preset: "as_specified" })}
          disabled={create.isPending}
        >
          {create.isPending ? "Creating…" : "New paper instance"}
        </Button>
      </div>

      {template?.warning && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm text-amber-400/90">
          {template.warning}
        </p>
      )}
      {create.isError && (
        <p className="text-xs text-red-400">{(create.error as Error).message}</p>
      )}

      <div className="flex flex-col gap-3">
        {instances?.length === 0 && (
          <p className="text-sm text-fg-faint">No instances yet.</p>
        )}
        {instances?.map((inst) => <InstanceCard key={inst.id} inst={inst} />)}
      </div>

      {template && (
        <Card>
          <CardHeader>
            <CardTitle>Parameters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-fg-faint">
                  <tr>
                    <th className="py-1 pr-4">Name</th>
                    <th className="py-1 pr-4">Type</th>
                    <th className="py-1 pr-4">Default</th>
                    <th className="py-1">Description</th>
                  </tr>
                </thead>
                <tbody className="text-fg-muted">
                  {Object.entries(template.parameters).map(([name, spec]) => (
                    <tr key={name} className="border-t border-line">
                      <td className="py-1.5 pr-4 font-mono text-[11px]">{name}</td>
                      <td className="py-1.5 pr-4">{spec.type}</td>
                      <td className="py-1.5 pr-4 font-mono text-[11px]">{String(spec.default)}</td>
                      <td className="py-1.5 text-fg-muted">{spec.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function InstanceCard({ inst }: { inst: OptionsInstance }) {
  const evaluate = useEvaluateOptionsInstance(inst.id);
  const enter = useEnterOptionsInstance(inst.id);
  const exit = useExitOptionsInstance(inst.id);
  const isOpen = inst.status === "ACTIVE";
  const distToShort =
    inst.last_spot != null && inst.strike_b != null ? inst.strike_b - inst.last_spot : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>
            {inst.underlying} {inst.expiry} · {inst.mode}
          </CardTitle>
          <Badge
            variant={
              inst.status === "ACTIVE"
                ? "info"
                : ["TARGET_HIT"].includes(inst.status)
                  ? "success"
                  : ["STOP_LOSS", "SHORT_STRIKE_EXIT", "FAILED"].includes(inst.status)
                    ? "destructive"
                    : "default"
            }
          >
            {inst.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {inst.not_eligible_reason && (
          <p className="text-xs text-amber-400/90">Not eligible: {inst.not_eligible_reason}</p>
        )}
        {inst.strike_a != null && (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-fg-muted sm:grid-cols-3">
            <Field label="Structure" value={`BUY 1 ${fmt(inst.strike_a, 0)} / SELL 3 ${fmt(inst.strike_b, 0)} / BUY 2 ${fmt(inst.strike_c, 0)} CE`} />
            <Field label="Lot size" value={fmt(inst.lot_size, 0)} />
            <Field label="Spot @ entry" value={fmt(inst.spot_at_entry, 1)} />
            <Field label="Deployed capital" value={`₹${fmt(inst.deployed_capital, 0)} (${inst.deployed_capital_source})`} />
            <Field label="Initial credit" value={`₹${fmt(inst.net_credit, 0)} (${fmt(inst.credit_pct)}%)`} />
            <Field label="Target / Stop" value={`₹${fmt(inst.target_amount, 0)} / ₹${fmt(inst.stop_loss_amount, 0)}`} />
            <Field label="Current P&L" value={`₹${fmt(inst.last_pnl, 0)}`} />
            <Field label="Spot / Short strike" value={`${fmt(inst.last_spot, 1)} / ${fmt(inst.strike_b, 0)}`} />
            <Field label="Distance to short" value={fmt(distToShort, 1)} />
            {inst.exit_reason && <Field label="Exit" value={`${inst.exit_reason} · net ₹${fmt(inst.net_pnl, 0)}`} />}
          </div>
        )}
        <div className="flex gap-2">
          {ACTIVE_STATUSES.includes(inst.status) && !isOpen && (
            <>
              <Button size="sm" variant="outline" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
                {evaluate.isPending ? "…" : "Evaluate now"}
              </Button>
              <Button size="sm" onClick={() => enter.mutate()} disabled={enter.isPending}>
                {enter.isPending ? "…" : "Enter (paper)"}
              </Button>
            </>
          )}
          {isOpen && (
            <Button size="sm" variant="destructive" onClick={() => exit.mutate()} disabled={exit.isPending}>
              {exit.isPending ? "…" : "Manual exit"}
            </Button>
          )}
        </div>
        {evaluate.data && (
          <p className={`text-xs ${evaluate.data.eligible ? "text-emerald-400" : "text-amber-400/90"}`}>
            {evaluate.data.reason}
            {evaluate.data.spot != null && ` · spot ${fmt(evaluate.data.spot, 1)}`}
            {evaluate.data.dte != null && ` · DTE ${evaluate.data.dte}`}
          </p>
        )}
        {[evaluate, enter, exit].map(
          (m, i) =>
            m.isError && (
              <p key={i} className="text-xs text-red-400">
                {(m.error as Error).message}
              </p>
            ),
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-fg-faint">{label}: </span>
      {value}
    </div>
  );
}
