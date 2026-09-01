import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ModeBadge } from "@/components/ModeBadge";
import { useCreateDeployment, useDeployments } from "@/hooks/useDeployments";
import { useStrategies } from "@/hooks/useStrategies";
import type { TradingMode } from "@/types/api";

const STATUS_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "info"> = {
  pending: "default",
  running: "success",
  paused: "warning",
  stopped: "default",
  error: "destructive",
};

const LIVE_CONFIRMATION_PHRASE = "DEPLOY LIVE TRADING";

export default function DeploymentsPage() {
  const { data: deployments, isLoading } = useDeployments();
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Deployments</h1>
          <p className="text-sm text-fg-muted">
            Simulation, paper, and live are strictly separate — a deployment's mode never changes
            after creation.
          </p>
        </div>
        <Button onClick={() => setShowForm((s) => !s)}>{showForm ? "Cancel" : "New deployment"}</Button>
      </div>

      {showForm && <CreateDeploymentForm onDone={() => setShowForm(false)} />}

      {isLoading && <p className="text-sm text-fg-faint">Loading…</p>}

      <div className="flex flex-col gap-2">
        {deployments?.map((d) => (
          <Link
            key={d.id}
            to={`/deployments/${d.id}`}
            className="flex items-center justify-between rounded-md border border-line px-4 py-3 hover:bg-elevated/60"
          >
            <div>
              <p className="text-sm font-medium">{d.name}</p>
              <p className="text-xs text-fg-faint">
                {d.instrument_universe.join(", ")}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant={STATUS_VARIANT[d.status]}>{d.status}</Badge>
              <ModeBadge mode={d.mode} />
            </div>
          </Link>
        ))}
        {deployments?.length === 0 && !isLoading && (
          <p className="text-sm text-fg-faint">No deployments yet.</p>
        )}
      </div>
    </div>
  );
}

function CreateDeploymentForm({ onDone }: { onDone: () => void }) {
  const { data: strategies } = useStrategies();
  const [strategyId, setStrategyId] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<TradingMode>("simulation");
  const [universe, setUniverse] = useState("NSE:INFY");
  const [confirmationText, setConfirmationText] = useState("");
  const create = useCreateDeployment();

  const strategy = strategies?.find((s) => s.id === strategyId);
  const isLive = mode === "live";
  const canSubmitLive = !isLive || confirmationText === LIVE_CONFIRMATION_PHRASE;

  return (
    <Card className={isLive ? "border-red-500/50" : undefined}>
      <CardHeader>
        <CardTitle>New deployment</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!strategy?.current_version_id) return;
            create.mutate(
              {
                strategy_version_id: strategy.current_version_id,
                name,
                mode,
                instrument_universe: universe.split(",").map((s) => s.trim()),
                live_trading_confirmation_phrase: isLive ? confirmationText : undefined,
              },
              { onSuccess: onDone },
            );
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="strategy">Strategy (current version is used)</Label>
            <select
              id="strategy"
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              required
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              <option value="">Select a strategy…</option>
              {strategies?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Deployment name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="universe">Instrument universe (comma-separated)</Label>
            <Input id="universe" value={universe} onChange={(e) => setUniverse(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Mode</Label>
            <div className="flex gap-2">
              {(["simulation", "paper", "live"] as TradingMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                    mode === m
                      ? m === "live"
                        ? "border-red-500 bg-red-500/10 text-neg"
                        : "border-pos/60 bg-pos/10 text-pos"
                      : "border-line-strong text-fg-muted hover:bg-elevated"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {isLive && (
            <div className="flex flex-col gap-2 rounded-md border border-red-500/50 bg-red-500/5 p-3">
              <div className="flex items-center gap-2 text-neg">
                <AlertTriangle className="h-4 w-4" />
                <p className="text-sm font-semibold">
                  This deployment will place real orders with real money through your connected
                  Zerodha account.
                </p>
              </div>
              <p className="text-xs text-red-300/80">
                Type <span className="font-mono font-semibold">{LIVE_CONFIRMATION_PHRASE}</span>{" "}
                exactly to confirm. This is checked again on every single order the backend places
                — not just at creation.
              </p>
              <Input
                value={confirmationText}
                onChange={(e) => setConfirmationText(e.target.value)}
                placeholder={LIVE_CONFIRMATION_PHRASE}
                className="font-mono"
              />
            </div>
          )}

          {create.isError && (
            <p className="text-xs text-neg">{(create.error as Error).message}</p>
          )}

          <div>
            <Button
              type="submit"
              variant={isLive ? "destructive" : "default"}
              disabled={create.isPending || !strategyId || !canSubmitLive}
            >
              {create.isPending ? "Creating…" : isLive ? "Create LIVE deployment" : "Create deployment"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
