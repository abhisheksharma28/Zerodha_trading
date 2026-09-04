import { Fragment, useMemo, useState } from "react";

import type { ScreenRow, SearchTopRow } from "@/api/discovery";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useDiscoveryRuns,
  useDiscoveryScreen,
  useDiscoveryUniverse,
  useRunDiscoverySearch,
} from "@/hooks/useDiscovery";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

const VERDICT_BADGE: Record<string, string> = {
  pass: "bg-pos/15 text-pos",
  downgrade: "bg-amber-500/15 text-amber-500",
  reject: "bg-neg/15 text-neg",
};

function K({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-md border border-line bg-elevated px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div
        className={cn(
          "font-mono text-sm",
          tone === "pos" && "text-pos",
          tone === "neg" && "text-neg",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function assetList(weights: Record<string, number>) {
  return Object.entries(weights)
    .sort((a, b) => b[1] - a[1])
    .map(([s, w]) => `${s} ${(w * 100).toFixed(0)}%`)
    .join(" · ");
}

// -------------------------------------------------------- universe

function UniverseStrip() {
  const { data, isLoading } = useDiscoveryUniverse();
  if (isLoading || !data) return <p className="text-sm text-fg-faint">Loading universe…</p>;
  const notIngested = data.instruments.filter((i) => !i.ingested);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Universe — {data.n_ingested}/{data.n_defined} ingested
          {data.tier_a_common_start ? ` · Tier-A common history from ${data.tier_a_common_start}` : ""}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.by_tier).map(([t, n]) => (
            <K key={t} label={`Tier ${t}`} value={String(n)} />
          ))}
          {Object.entries(data.by_asset_class).map(([c, n]) => (
            <K key={c} label={c} value={String(n)} />
          ))}
          {Object.entries(data.fx).map(([p, n]) => (
            <K key={p} label={p} value={`${n} pts`} />
          ))}
        </div>
        {notIngested.length > 0 && (
          <p className="text-xs text-fg-faint">
            Not yet ingested ({notIngested.length}):{" "}
            {notIngested.map((i) => i.symbol).join(", ")} — set{" "}
            <code className="text-fg-muted">TWELVEDATA_API_KEY</code> and run{" "}
            <code className="text-fg-muted">python -m app.discovery.ingest fetch</code>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// -------------------------------------------------------- screen

function ScreenTable() {
  const { data, isLoading } = useDiscoveryScreen();
  const rows = data?.instruments ?? [];
  const columns: Column<ScreenRow>[] = [
    { key: "symbol", header: "Symbol", sortValue: (r) => r.symbol, cell: (r) => <span className="font-medium">{r.symbol}</span> },
    { key: "score", header: "Screen", align: "right", sortValue: (r) => r.screen_score, cell: (r) => <span className="font-mono">{num(r.screen_score, 1)}</span> },
    { key: "cagr", header: "CAGR %", align: "right", sortValue: (r) => r.metrics.cagr_pct ?? -999, cell: (r) => num(r.metrics.cagr_pct, 1) },
    { key: "vol", header: "Vol %", align: "right", sortValue: (r) => r.metrics.ann_vol_pct ?? 999, cell: (r) => num(r.metrics.ann_vol_pct, 1) },
    { key: "sharpe", header: "Sharpe", align: "right", sortValue: (r) => r.metrics.sharpe ?? -999, cell: (r) => num(r.metrics.sharpe, 2) },
    { key: "dd", header: "Max DD %", align: "right", sortValue: (r) => r.metrics.max_drawdown_pct ?? -999, cell: (r) => <span className="text-neg">{num(r.metrics.max_drawdown_pct, 1)}</span> },
    { key: "corr", header: "Corr mkt", align: "right", sortValue: (r) => r.metrics.corr_to_market ?? 2, cell: (r) => (r.metrics.corr_to_market == null ? "—" : num(r.metrics.corr_to_market, 2)) },
    { key: "cluster", header: "Cluster", align: "center", sortValue: (r) => r.cluster ?? -1, cell: (r) => (r.cluster == null ? "—" : `#${r.cluster}`) },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Instrument screen{data ? ` · ${data.n} scored · ${data.period_start ?? "?"} → ${data.period_end ?? "?"}` : ""}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <p className="p-4 text-sm text-fg-faint">Scoring…</p>
        ) : rows.length === 0 ? (
          <p className="p-4 text-sm text-fg-faint">
            No ingested Tier A/B instruments yet — ingest the universe first.
          </p>
        ) : (
          <DataTable columns={columns} rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "score", dir: "desc" }} />
        )}
      </CardContent>
    </Card>
  );
}

// -------------------------------------------------------- validation detail

function ValidationDetail({ row }: { row: SearchTopRow }) {
  const v = row.validation;
  const reg = Object.entries(row.by_regime);
  return (
    <div className="flex flex-col gap-3 border-t border-line bg-elevated/40 p-4 text-xs">
      <div>
        <span className="text-fg-faint">Weights: </span>
        <span className="font-mono">{assetList(row.weights)}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(row.category_scores).map(([c, s]) => (
          <span key={c} className="rounded bg-surface px-2 py-1">
            {c} <span className="font-mono text-fg-muted">{num(s, 0)}</span>
          </span>
        ))}
      </div>
      {reg.length > 0 && (
        <div>
          <span className="text-fg-faint">By regime: </span>
          {reg.map(([rg, b]) => (
            <span key={rg} className="mr-3">
              {rg} <span className={cn("font-mono", b.return_pct >= 0 ? "text-pos" : "text-neg")}>{num(b.return_pct, 1)}%</span>
              <span className="text-fg-faint"> (n{b.n})</span>
            </span>
          ))}
        </div>
      )}
      {v ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={VERDICT_BADGE[v.verdict]}>{v.verdict}</Badge>
            <span>
              Stability <span className="font-mono">{num(v.stability_score, 0)}</span> · {v.label}
            </span>
            {v.deflated_sharpe != null && (
              <span className="text-fg-muted">
                DSR <span className="font-mono">{num(v.deflated_sharpe, 2)}</span>
              </span>
            )}
            {v.psr != null && (
              <span className="text-fg-muted">
                PSR <span className="font-mono">{num(v.psr, 2)}</span>
              </span>
            )}
          </div>
          {v.block_bootstrap.available && v.block_bootstrap.cagr_pct && (
            <div className="text-fg-muted">
              Bootstrap CAGR p5/p50/p95:{" "}
              <span className="font-mono">
                {num(v.block_bootstrap.cagr_pct["5"], 1)} / {num(v.block_bootstrap.cagr_pct["50"], 1)} /{" "}
                {num(v.block_bootstrap.cagr_pct["95"], 1)}%
              </span>{" "}
              · P(neg CAGR) <span className="font-mono">{num(v.block_bootstrap.prob_negative_cagr, 2)}</span>
            </div>
          )}
          {v.perturbation.available && (
            <div className="text-fg-muted">
              Weight perturbation: max drop <span className="font-mono">{num(v.perturbation.max_drop, 1)}</span> pts
              {v.perturbation.fragile ? <span className="text-neg"> · fragile</span> : <span className="text-pos"> · stable</span>}
            </div>
          )}
          {v.start_date_sensitivity.available && (
            <div className="text-fg-muted">
              Start-date sweep: Sharpe worst/median{" "}
              <span className="font-mono">
                {num(v.start_date_sensitivity.sharpe_worst, 2)} / {num(v.start_date_sensitivity.sharpe_median, 2)}
              </span>{" "}
              ({v.start_date_sensitivity.windows} windows)
            </div>
          )}
          {v.rejections.length > 0 && (
            <ul className="list-inside list-disc text-neg">
              {v.rejections.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-fg-faint">Not validated (outside top {"validate_top"}).</p>
      )}
    </div>
  );
}

// -------------------------------------------------------- search

function SearchPanel() {
  const run = useRunDiscoverySearch();
  const [method, setMethod] = useState<"monte_carlo" | "genetic">("monte_carlo");
  const [nPortfolios, setNPortfolios] = useState(1500);
  const [seed, setSeed] = useState(7);
  const [wmax, setWmax] = useState(0.35);
  const [validateTop, setValidateTop] = useState(5);
  const [open, setOpen] = useState<number | null>(null);

  const res = run.data;
  const rows = res?.available ? res.top : [];

  const pareto = useMemo(
    () => (res?.available ? res.pareto_frontier.slice().sort((a, b) => b.alpha_score - a.alpha_score) : []),
    [res],
  );

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>Method</Label>
              <div className="flex overflow-hidden rounded-md border border-line">
                {(["monte_carlo", "genetic"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMethod(m)}
                    className={cn(
                      "px-3 py-1.5 text-sm",
                      method === m ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-elevated",
                    )}
                  >
                    {m === "monte_carlo" ? "Monte Carlo" : "Genetic"}
                  </button>
                ))}
              </div>
            </div>
            {method === "monte_carlo" && (
              <div className="flex flex-col gap-1.5">
                <Label>Portfolios</Label>
                <Input
                  type="number"
                  value={nPortfolios}
                  min={100}
                  step={100}
                  onChange={(e) => setNPortfolios(Number(e.target.value) || 1500)}
                  className="w-28"
                />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label>Max weight</Label>
              <Input
                type="number"
                value={wmax}
                min={0.1}
                max={1}
                step={0.05}
                onChange={(e) => setWmax(Number(e.target.value) || 0.35)}
                className="w-24"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Validate top</Label>
              <Input
                type="number"
                value={validateTop}
                min={0}
                max={10}
                step={1}
                onChange={(e) => setValidateTop(Number(e.target.value) || 0)}
                className="w-20"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Seed</Label>
              <Input
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value) || 0)}
                className="w-20"
              />
            </div>
            <Button
              disabled={run.isPending}
              onClick={() =>
                run.mutate({
                  method,
                  n_portfolios: nPortfolios,
                  wmax,
                  seed,
                  validate_top: validateTop,
                })
              }
            >
              {run.isPending ? "Searching…" : "Run search"}
            </Button>
            {run.isError && <span className="text-xs text-neg">{(run.error as Error).message}</span>}
          </div>
          <p className="text-xs text-fg-faint">
            The candidate universe is picked automatically — the best-scored instrument per
            correlation cluster. Survivors are ranked by 0.6·alpha + 0.4·stability after
            adversarial validation.
          </p>
        </CardContent>
      </Card>

      {res && !res.available && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-fg-faint">{res.reason}</CardContent>
        </Card>
      )}

      {res?.available && (
        <Card>
          <CardHeader>
            <CardTitle>
              {res.method} · tested {res.tested} · kept {res.kept} · {res.elapsed_s}s
              {res.run_id ? ` · run ${res.run_id.slice(0, 8)}` : ""}
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-left text-xs">
              <thead className="text-fg-faint">
                <tr>
                  <th className="p-2">#</th>
                  <th className="p-2">Portfolio</th>
                  <th className="p-2 text-right">Alpha</th>
                  <th className="p-2 text-right">Final</th>
                  <th className="p-2 text-center">Verdict</th>
                  <th className="p-2 text-right">Stab.</th>
                  <th className="p-2 text-right">CAGR %</th>
                  <th className="p-2 text-right">Sharpe</th>
                  <th className="p-2 text-right">Max DD %</th>
                  <th className="p-2 text-right">Eff. N</th>
                  <th className="p-2 text-center">Pareto</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <Fragment key={r.rank}>
                    <tr
                      className="cursor-pointer border-t border-line hover:bg-elevated/60"
                      onClick={() => setOpen(open === i ? null : i)}
                    >
                      <td className="p-2 font-mono">{r.rank}</td>
                      <td className="max-w-[22rem] truncate p-2 font-mono" title={assetList(r.weights)}>
                        {assetList(r.weights)}
                      </td>
                      <td className="p-2 text-right font-mono">{num(r.alpha_score, 1)}</td>
                      <td className="p-2 text-right font-mono">
                        {r.final_score == null ? "—" : num(r.final_score, 1)}
                      </td>
                      <td className="p-2 text-center">
                        {r.validation ? (
                          <Badge className={VERDICT_BADGE[r.validation.verdict]}>
                            {r.validation.verdict}
                          </Badge>
                        ) : (
                          <span className="text-fg-faint">—</span>
                        )}
                      </td>
                      <td className="p-2 text-right font-mono">
                        {r.validation ? num(r.validation.stability_score, 0) : "—"}
                      </td>
                      <td className="p-2 text-right font-mono">{num(r.metrics.cagr_pct, 1)}</td>
                      <td className="p-2 text-right font-mono">{num(r.metrics.sharpe, 2)}</td>
                      <td className="p-2 text-right font-mono text-neg">
                        {num(r.metrics.max_drawdown_pct, 1)}
                      </td>
                      <td className="p-2 text-right font-mono">{num(r.metrics.effective_n, 1)}</td>
                      <td className="p-2 text-center">{r.on_pareto_frontier ? "✓" : ""}</td>
                    </tr>
                    {open === i && (
                      <tr>
                        <td colSpan={11} className="p-0">
                          <ValidationDetail row={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {pareto.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Pareto frontier — {pareto.length} non-dominated portfolios</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-left text-xs">
              <thead className="text-fg-faint">
                <tr>
                  <th className="p-2">Portfolio</th>
                  <th className="p-2 text-right">Alpha</th>
                  <th className="p-2 text-right">CAGR %</th>
                  <th className="p-2 text-right">Sharpe</th>
                  <th className="p-2 text-right">Max DD %</th>
                </tr>
              </thead>
              <tbody>
                {pareto.map((p, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="max-w-[24rem] truncate p-2 font-mono" title={assetList(p.weights)}>
                      {assetList(p.weights)}
                    </td>
                    <td className="p-2 text-right font-mono">{num(p.alpha_score, 1)}</td>
                    <td className="p-2 text-right font-mono">{num(p.cagr_pct, 1)}</td>
                    <td className="p-2 text-right font-mono">{num(p.sharpe, 2)}</td>
                    <td className="p-2 text-right font-mono text-neg">{num(p.max_drawdown_pct, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </>
  );
}

// -------------------------------------------------------- recent runs

function RecentRuns() {
  const { data } = useDiscoveryRuns(15);
  if (!data || data.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent experiments</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-left text-xs">
          <thead className="text-fg-faint">
            <tr>
              <th className="p-2">When</th>
              <th className="p-2">Method</th>
              <th className="p-2 text-right">Tested</th>
              <th className="p-2 text-right">Kept</th>
              <th className="p-2 text-right">Survivors</th>
              <th className="p-2 text-right">Top alpha</th>
              <th className="p-2">Best survivor</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <td className="p-2">{new Date(r.started_at).toLocaleString()}</td>
                <td className="p-2">{r.method}</td>
                <td className="p-2 text-right font-mono">{r.n_tested}</td>
                <td className="p-2 text-right font-mono">{r.n_kept}</td>
                <td className="p-2 text-right font-mono">{r.n_survivors}</td>
                <td className="p-2 text-right font-mono">{r.top_alpha == null ? "—" : num(r.top_alpha, 1)}</td>
                <td className="max-w-[20rem] truncate p-2 font-mono">
                  {r.best_survivor ? assetList(r.best_survivor.weights) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export default function DiscoveryPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Alpha Discovery Engine"
        subtitle="Search a global multi-asset ETF universe for robust 5–10 instrument portfolios, then try to break them: deflated Sharpe, block bootstrap, weight perturbation, start-date sweep, and a stability score."
      />
      <UniverseStrip />
      <ScreenTable />
      <SearchPanel />
      <RecentRuns />
    </div>
  );
}
