import { useEffect, useMemo, useState } from "react";
import Editor from "@monaco-editor/react";

import type { EditorBacktestResult, ValidateResult } from "@/api/strategyEditor";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Sparkline } from "@/components/Sparkline";
import { TimeframeSelect } from "@/components/TimeframeSelect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useEditorBacktest,
  useEditorStarter,
  useSaveEditorStrategy,
  useValidateStrategy,
} from "@/hooks/useStrategyEditor";
import { inr, num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const LS_KEY = "strategy-editor-draft";

const METRIC_LABELS: [string, string][] = [
  ["return_pct", "Return %"],
  ["cagr_pct", "CAGR %"],
  ["sharpe_ratio", "Sharpe"],
  ["sortino_ratio", "Sortino"],
  ["max_drawdown_pct", "Max DD %"],
  ["win_rate_pct", "Win rate %"],
  ["profit_factor", "Profit factor"],
  ["total_trades", "Trades"],
  ["net_pnl", "Net P&L"],
  ["total_costs", "Costs"],
];

function Metrics({ m }: { m: Record<string, number | null> }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-5">
      {METRIC_LABELS.map(([k, label]) => {
        const v = m[k];
        const money = k === "net_pnl" || k === "total_costs";
        const pctKind = k.endsWith("_pct");
        const tone =
          k === "return_pct" || k === "cagr_pct" || k === "net_pnl"
            ? (v ?? 0) < 0
              ? "text-neg"
              : "text-pos"
            : k === "max_drawdown_pct" || k === "total_costs"
              ? "text-neg"
              : "";
        return (
          <div key={k} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
            <span className={cn("tabular-nums text-sm font-semibold", tone)}>
              {v == null
                ? "—"
                : money
                  ? inr(v)
                  : pctKind
                    ? pctSigned(v)
                    : num(v, k === "total_trades" ? 0 : 2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ValidationPanel({ v }: { v: ValidateResult }) {
  if (!v.ok) {
    return (
      <div className="rounded-md border border-neg/40 bg-neg/10 p-2 text-xs text-neg">
        <p className="font-semibold">
          {v.stage === "static-check" ? "Blocked by the safety check" : "Compile / load failed"}
        </p>
        <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{v.error}</pre>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-pos/40 bg-pos/10 p-2 text-xs">
      <p className="font-semibold text-pos">
        ✓ {v.name} — {Object.keys(v.params ?? {}).length} params, presets:{" "}
        {(v.presets ?? []).join(" / ")}
      </p>
      <p className="mt-0.5 text-fg-muted">
        timeframes {(v.supported_timeframes ?? []).join(", ")} · {v.min_instruments}
        {v.max_instruments ? `–${v.max_instruments}` : "+"} instruments
      </p>
    </div>
  );
}

function BacktestResult({ r }: { r: EditorBacktestResult }) {
  const curve = (r.equity_curve ?? []).map(([, val]) => Number(val));
  if (!r.ok) {
    return (
      <div className="rounded-md border border-neg/40 bg-neg/10 p-2 text-xs text-neg">
        <p className="font-semibold">Backtest failed{r.stage ? ` (${r.stage})` : ""}</p>
        <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{r.error}</pre>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-fg-muted">
        {r.name} · {r.timeframe} · {r.start} → {r.end} · {inr(r.capital ?? 0)} ·{" "}
        {(r.used_symbols ?? []).length} names
        {r.skipped && r.skipped.length > 0 && (
          <span className="text-fg-faint"> · {r.skipped.length} skipped</span>
        )}
      </p>
      {r.metrics && <Metrics m={r.metrics} />}
      {curve.length > 2 && (
        <div className="h-16 w-full">
          <Sparkline data={curve} tone={(r.metrics?.return_pct ?? 0) < 0 ? "neg" : "accent"} />
        </div>
      )}
      {r.per_symbol && r.per_symbol.length > 0 && (
        <div className="max-h-40 overflow-auto rounded border border-line text-[11px]">
          <table className="w-full">
            <thead className="sticky top-0 bg-elevated text-fg-faint">
              <tr>
                <th className="px-2 py-1 text-left">Symbol</th>
                <th className="px-2 py-1 text-right">Trades</th>
                <th className="px-2 py-1 text-right">Net P&L</th>
                <th className="px-2 py-1 text-right">Win %</th>
              </tr>
            </thead>
            <tbody>
              {r.per_symbol.map((s) => (
                <tr key={s.symbol} className="border-t border-line/60">
                  <td className="px-2 py-1 font-medium text-fg">{s.symbol}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{s.trades}</td>
                  <td
                    className={cn(
                      "px-2 py-1 text-right tabular-nums",
                      s.net_pnl < 0 ? "text-neg" : "text-pos",
                    )}
                  >
                    {inr(s.net_pnl)}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{num(s.win_rate_pct, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.caveats && r.caveats.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-fg-faint">
          {r.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function StrategyEditorPage() {
  const { data: starter } = useEditorStarter();
  const [code, setCode] = useState<string>(() => {
    try {
      return localStorage.getItem(LS_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [symbols, setSymbols] = useState<string[]>(["NSE:RELIANCE", "NSE:INFY", "NSE:HDFCBANK"]);
  const [timeframe, setTimeframe] = useState("1d");
  const [preset, setPreset] = useState("balanced");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [capital, setCapital] = useState(1_000_000);
  const [showApi, setShowApi] = useState(true);

  const validate = useValidateStrategy();
  const backtest = useEditorBacktest();
  const save = useSaveEditorStrategy();

  // seed the editor from the server starter once, only if there's no draft
  useEffect(() => {
    setCode((c) => (c ? c : (starter?.source ?? c)));
  }, [starter?.source]);

  useEffect(() => {
    const t = setTimeout(() => {
      try {
        if (code) localStorage.setItem(LS_KEY, code);
      } catch {
        /* private mode */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [code]);

  const presets = validate.data?.ok ? (validate.data.presets ?? ["balanced"]) : ["conservative", "balanced", "aggressive"];
  const canRun = code.trim().length > 20 && symbols.length > 0;
  const running = validate.isPending || backtest.isPending;

  const apiLines = useMemo(() => {
    const a = starter?.api;
    if (!a) return [];
    return [
      `Base class: ${a.base_class}`,
      `Define: ${a.must_define}`,
      a.on_bar,
      ...a.helpers.map((h) => `• ${h}`),
      a.indicators,
      `Allowed imports: ${a.allowed_imports}`,
      `Sandbox: ${a.limits}`,
    ];
  }, [starter?.api]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Python strategy editor"
        subtitle="Write a strategy in Python, compile it in the sandbox, and backtest it against real NSE history — the same engine the library strategies use."
        actions={
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={running || !code.trim()}
              onClick={() => validate.mutate(code)}
            >
              {validate.isPending ? "Compiling…" : "Validate"}
            </Button>
            <Button
              size="sm"
              disabled={running || !canRun}
              onClick={() =>
                backtest.mutate({
                  source: code,
                  symbols,
                  timeframe,
                  preset,
                  capital,
                  start: start || undefined,
                  end: end || undefined,
                })
              }
              className="bg-[#4184f3] hover:bg-[#356fd0]"
            >
              {backtest.isPending ? "Running backtest…" : "Run backtest"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={running || !validate.data?.ok}
              onClick={() => {
                const name = window.prompt("Save as (strategy name):", validate.data?.name ?? "My strategy");
                if (name) save.mutate({ source: code, name });
              }}
            >
              Save to My Strategies
            </Button>
          </div>
        }
      />

      {save.isSuccess && (
        <div className="rounded-md border border-pos/40 bg-pos/10 px-3 py-2 text-sm text-pos">
          Saved “{save.data.name}”. It’s now in My Strategies and can be deployed / backtested there.
        </div>
      )}
      {save.isError && (
        <div className="rounded-md border border-neg/40 bg-neg/10 px-3 py-2 text-sm text-neg">
          Could not save — validate the strategy first.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SectionCard title="strategy.py" bodyClassName="p-0">
            <Editor
              height="58vh"
              defaultLanguage="python"
              value={code}
              onChange={(v) => setCode(v ?? "")}
              theme="vs-dark"
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                tabSize: 4,
                automaticLayout: true,
                padding: { top: 10 },
              }}
            />
          </SectionCard>
        </div>

        <div className="flex flex-col gap-3">
          {validate.data && <ValidationPanel v={validate.data} />}

          <SectionCard
            title="Backtest"
            actions={
              <button
                type="button"
                onClick={() => setShowApi((s) => !s)}
                className="text-[11px] text-accent hover:underline"
              >
                {showApi ? "Hide API" : "Show API"}
              </button>
            }
          >
            <div className="flex flex-col gap-2.5">
              <div className="flex flex-col gap-1">
                <Label>Instruments</Label>
                <InstrumentSearch value={symbols} onChange={setSymbols} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1">
                  <Label>Timeframe</Label>
                  <TimeframeSelect value={timeframe} onChange={setTimeframe} />
                </div>
                <div className="flex flex-col gap-1">
                  <Label>Preset</Label>
                  <select
                    value={preset}
                    onChange={(e) => setPreset(e.target.value)}
                    className="h-9 rounded-md border border-line-strong bg-surface px-2 text-sm text-fg"
                  >
                    {presets.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="s">Start</Label>
                  <Input id="s" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="e">End</Label>
                  <Input id="e" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="cap">Capital (₹)</Label>
                <Input
                  id="cap"
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value) || 0)}
                />
              </div>
            </div>
          </SectionCard>

          {showApi && (
            <SectionCard title="API cheat-sheet">
              <ul className="space-y-1 text-[11px] text-fg-muted">
                {apiLines.map((l, i) => (
                  <li key={i} className="font-mono">
                    {l}
                  </li>
                ))}
              </ul>
            </SectionCard>
          )}
        </div>
      </div>

      {backtest.data && (
        <SectionCard
          title={
            <span className="flex items-center gap-2">
              Backtest result
              {backtest.data.ok && backtest.data.generated_at && (
                <Badge variant="default" className="text-[10px]">
                  {new Date(backtest.data.generated_at).toLocaleTimeString("en-IN")}
                </Badge>
              )}
            </span>
          }
        >
          <BacktestResult r={backtest.data} />
        </SectionCard>
      )}

      <p className="text-[11px] text-fg-faint">
        User code runs in a subprocess with CPU / memory / time limits and an import allow-list, not a
        full container sandbox. Results are screener output over one window — not investment advice.
      </p>
    </div>
  );
}
