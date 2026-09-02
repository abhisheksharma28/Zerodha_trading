import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { backtestsApi } from "@/api/backtests";
import {
  backtestKeys,
  useBacktests,
  useCreateBacktest,
  useDeleteBacktest,
} from "@/hooks/useBacktests";
import { useStrategies } from "@/hooks/useStrategies";
import { inr } from "@/lib/format";
import type { Backtest } from "@/types/api";

const STATUS_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "info"> = {
  pending: "default",
  running: "info",
  completed: "success",
  failed: "destructive",
  cancelled: "default",
};

export default function BacktestsPage() {
  const { data: backtests, isLoading } = useBacktests();
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Backtests</h1>
          <p className="text-sm text-fg-muted">
            Runs the exact same strategy code that simulation/paper/live use, against historical
            candles.
          </p>
        </div>
        <Button onClick={() => setShowForm((s) => !s)}>{showForm ? "Cancel" : "New backtest"}</Button>
      </div>

      {showForm && <CreateBacktestForm onDone={() => setShowForm(false)} />}

      {isLoading && <p className="text-sm text-fg-faint">Loading…</p>}

      <div className="flex flex-col gap-2">
        {backtests?.map((bt) => (
          <BacktestRow key={bt.id} bt={bt} />
        ))}
        {backtests?.length === 0 && !isLoading && (
          <p className="text-sm text-fg-faint">No backtests yet.</p>
        )}
      </div>
    </div>
  );
}

function BacktestRow({ bt }: { bt: Backtest }) {
  const del = useDeleteBacktest();

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-line px-4 py-3 hover:bg-elevated/60">
      <Link to={`/backtests/${bt.id}`} className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {bt.instrument_universe.join(", ")} · {bt.timeframe}
        </p>
        <p className="text-xs text-fg-faint">
          {new Date(bt.start_date).toLocaleDateString()} –{" "}
          {new Date(bt.end_date).toLocaleDateString()} · {inr(bt.initial_capital)}
        </p>
      </Link>
      <div className="flex shrink-0 items-center gap-3">
        {bt.metrics && (
          <span className="text-xs text-fg-muted">
            {bt.metrics.total_return_pct?.toFixed(2)}% return
          </span>
        )}
        <Badge variant={STATUS_VARIANT[bt.status]}>{bt.status}</Badge>
        <Button
          variant="ghost"
          size="sm"
          className="text-neg hover:text-neg"
          disabled={del.isPending}
          onClick={() => {
            if (window.confirm("Delete this backtest? Its stored orders are removed too. This cannot be undone."))
              del.mutate(bt.id);
          }}
        >
          {del.isPending ? "Deleting…" : "Delete"}
        </Button>
      </div>
    </div>
  );
}

function CreateBacktestForm({ onDone }: { onDone: () => void }) {
  const { data: strategies } = useStrategies();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [strategyId, setStrategyId] = useState("");
  const [universe, setUniverse] = useState<string[]>(["NSE:INFY"]);
  const [timeframe, setTimeframe] = useState("1d");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [capital, setCapital] = useState(100000);
  const [sizing, setSizing] = useState("");
  const [qty, setQty] = useState(1);
  const [riskPct, setRiskPct] = useState(1);
  const [targetVolPct, setTargetVolPct] = useState(2);
  const [maxPosPct, setMaxPosPct] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const create = useCreateBacktest();

  function buildOverrides(): Record<string, unknown> {
    const o: Record<string, unknown> = {};
    if (sizing) {
      o.sizing_method = sizing;
      if (sizing === "fixed_quantity") o.fixed_quantity = qty;
      if (sizing === "risk_per_trade") o.risk_per_trade_pct = riskPct;
      if (sizing === "volatility_adjusted") o.target_volatility_pct = targetVolPct;
    }
    if (maxPosPct.trim() !== "") o.max_position_size_pct = Number(maxPosPct);
    return o;
  }

  const strategy = strategies?.find((s) => s.id === strategyId);
  const busy = create.isPending || running;

  return (
    <Card>
      <CardHeader>
        <CardTitle>New backtest</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!strategy?.current_version_id || universe.length === 0 || busy) return;
            setRunError(null);
            create.mutate(
              {
                strategy_version_id: strategy.current_version_id,
                instrument_universe: universe,
                timeframe,
                start_date: new Date(startDate).toISOString(),
                end_date: new Date(endDate).toISOString(),
                initial_capital: capital,
              },
              {
                onSuccess: async (bt) => {
                  setRunning(true);
                  try {
                    const overrides = buildOverrides();
                    await backtestsApi.run(
                      bt.id,
                      Object.keys(overrides).length ? { parameter_overrides: overrides } : {},
                    );
                  } catch (err) {
                    setRunError((err as Error).message);
                  } finally {
                    setRunning(false);
                    queryClient.invalidateQueries({ queryKey: backtestKeys.all });
                    queryClient.invalidateQueries({ queryKey: backtestKeys.detail(bt.id) });
                    onDone();
                    navigate(`/backtests/${bt.id}`);
                  }
                },
              },
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
            <Label>Instrument universe</Label>
            <InstrumentSearch value={universe} onChange={setUniverse} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Timeframe</Label>
            <TimeframeSelect value={timeframe} onChange={setTimeframe} />
            <p className="text-xs text-fg-faint">
              The backtest is rejected with a clear reason if the strategy doesn't support this
              timeframe.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="start">Start date</Label>
              <Input
                id="start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="end">End date</Label>
              <Input
                id="end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="capital">Initial capital (₹)</Label>
            <Input
              id="capital"
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </div>

          <div className="rounded-md border border-line bg-elevated/40 p-3">
            <p className="mb-2 text-xs font-medium text-fg-muted">
              Position sizing (overrides the strategy's saved parameters for this run only)
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="sizing">Method</Label>
                <select
                  id="sizing"
                  value={sizing}
                  onChange={(e) => setSizing(e.target.value)}
                  className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
                >
                  <option value="">Strategy default</option>
                  <option value="fixed_quantity">Fixed quantity</option>
                  <option value="fixed_capital">Fixed capital (all-in)</option>
                  <option value="equal_weight">Equal weight</option>
                  <option value="volatility_adjusted">Volatility-adjusted</option>
                  <option value="risk_per_trade">Risk % per trade</option>
                </select>
              </div>

              {sizing === "fixed_quantity" && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="qty">Quantity per order</Label>
                  <Input
                    id="qty"
                    type="number"
                    min={1}
                    value={qty}
                    onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
                  />
                </div>
              )}
              {sizing === "risk_per_trade" && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="riskpct">Risk % per trade</Label>
                  <Input
                    id="riskpct"
                    type="number"
                    step="0.1"
                    min={0.01}
                    value={riskPct}
                    onChange={(e) => setRiskPct(Number(e.target.value) || 0)}
                  />
                </div>
              )}
              {sizing === "volatility_adjusted" && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="tvol">Target volatility %</Label>
                  <Input
                    id="tvol"
                    type="number"
                    step="0.1"
                    min={0.01}
                    value={targetVolPct}
                    onChange={(e) => setTargetVolPct(Number(e.target.value) || 0)}
                  />
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="maxpos">Max position size % (optional)</Label>
                <Input
                  id="maxpos"
                  type="number"
                  step="1"
                  placeholder="strategy default"
                  value={maxPosPct}
                  onChange={(e) => setMaxPosPct(e.target.value)}
                />
              </div>
            </div>
          </div>
          {create.isError && (
            <p className="text-xs text-neg">{(create.error as Error).message}</p>
          )}
          {runError && <p className="text-xs text-neg">{runError}</p>}
          <div>
            <Button
              type="submit"
              disabled={busy || !strategyId || universe.length === 0}
            >
              {create.isPending ? "Creating…" : running ? "Running…" : "Create & run backtest"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
