import { useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBacktest } from "@/hooks/useBacktests";

export default function BacktestDetailPage() {
  const { backtestId } = useParams<{ backtestId: string }>();
  const { data: backtest, isLoading } = useBacktest(backtestId);

  if (isLoading) return <p className="text-sm text-neutral-500">Loading…</p>;
  if (!backtest) return <p className="text-sm text-neutral-500">Backtest not found.</p>;

  const chartData = (backtest.equity_curve ?? []).map(([ts, value], i) => ({
    index: i,
    ts,
    equity: value,
  }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {backtest.instrument_universe.join(", ")} backtest
          </h1>
          <p className="text-sm text-neutral-400">
            {new Date(backtest.start_date).toLocaleDateString()} –{" "}
            {new Date(backtest.end_date).toLocaleDateString()}
          </p>
        </div>
        <Badge variant={backtest.status === "completed" ? "success" : "default"}>
          {backtest.status}
        </Badge>
      </div>

      {backtest.error_message && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="py-3 text-sm text-red-400">
            {backtest.error_message}
          </CardContent>
        </Card>
      )}

      {backtest.metrics && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Metric label="Total return" value={`${backtest.metrics.total_return_pct?.toFixed(2)}%`} />
          <Metric label="CAGR" value={`${backtest.metrics.cagr_pct?.toFixed(2)}%`} />
          <Metric
            label="Max drawdown"
            value={`${backtest.metrics.max_drawdown_pct?.toFixed(2)}%`}
            negative
          />
          <Metric label="Sharpe" value={backtest.metrics.sharpe_ratio?.toFixed(2) ?? "–"} />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Equity curve</CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <p className="text-sm text-neutral-500">
              No equity curve yet — this backtest hasn't been executed. Running a backtest requires
              cached historical candles (see app.market_data.cache) fetched via a connected broker
              session.
            </p>
          ) : (
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                  <XAxis dataKey="index" stroke="#737373" fontSize={12} />
                  <YAxis stroke="#737373" fontSize={12} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ background: "#171717", border: "1px solid #404040" }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.ts ?? ""}
                  />
                  <Line type="monotone" dataKey="equity" stroke="#10b981" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value, negative }: { label: string; value: string; negative?: boolean }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
        <p className={`mt-1 text-xl font-semibold ${negative ? "text-red-400" : "text-neutral-100"}`}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
