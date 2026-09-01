import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useBacktests, useCreateBacktest } from "@/hooks/useBacktests";
import { useStrategies } from "@/hooks/useStrategies";

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
          <Link
            key={bt.id}
            to={`/backtests/${bt.id}`}
            className="flex items-center justify-between rounded-md border border-line px-4 py-3 hover:bg-elevated/60"
          >
            <div>
              <p className="text-sm font-medium">
                {bt.instrument_universe.join(", ")} · {bt.timeframe}
              </p>
              <p className="text-xs text-fg-faint">
                {new Date(bt.start_date).toLocaleDateString()} –{" "}
                {new Date(bt.end_date).toLocaleDateString()} · ₹{bt.initial_capital.toLocaleString()}
              </p>
            </div>
            <div className="flex items-center gap-3">
              {bt.metrics && (
                <span className="text-xs text-fg-muted">
                  {bt.metrics.total_return_pct?.toFixed(2)}% return
                </span>
              )}
              <Badge variant={STATUS_VARIANT[bt.status]}>{bt.status}</Badge>
            </div>
          </Link>
        ))}
        {backtests?.length === 0 && !isLoading && (
          <p className="text-sm text-fg-faint">No backtests yet.</p>
        )}
      </div>
    </div>
  );
}

function CreateBacktestForm({ onDone }: { onDone: () => void }) {
  const { data: strategies } = useStrategies();
  const [strategyId, setStrategyId] = useState("");
  const [universe, setUniverse] = useState<string[]>(["NSE:INFY"]);
  const [timeframe, setTimeframe] = useState("1d");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [capital, setCapital] = useState(100000);
  const create = useCreateBacktest();

  const strategy = strategies?.find((s) => s.id === strategyId);

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
            if (!strategy?.current_version_id || universe.length === 0) return;
            create.mutate(
              {
                strategy_version_id: strategy.current_version_id,
                instrument_universe: universe,
                timeframe,
                start_date: new Date(startDate).toISOString(),
                end_date: new Date(endDate).toISOString(),
                initial_capital: capital,
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
          {create.isError && (
            <p className="text-xs text-neg">{(create.error as Error).message}</p>
          )}
          <div>
            <Button
              type="submit"
              disabled={create.isPending || !strategyId || universe.length === 0}
            >
              {create.isPending ? "Creating…" : "Create backtest"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
