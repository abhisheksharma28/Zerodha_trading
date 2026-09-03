import { useMemo, useState } from "react";

import type { Product } from "@/api/paperAccount";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { useCreatePaperStrategy, usePaperStrategyTemplates } from "@/hooks/usePaperAccount";
import { cn } from "@/lib/utils";

const TF_LABEL: Record<string, string> = {
  "1m": "1 min", "3m": "3 min", "5m": "5 min", "15m": "15 min", "30m": "30 min",
  "1h": "1 hour", "1d": "Daily",
};
const PRODUCTS: Product[] = ["CNC", "MIS", "NRML"];
const KEY_PARAMS = ["capital_allocation", "sizing_method", "fixed_quantity"];

export function StrategyDeploy({ onDone }: { onDone: () => void }) {
  const { data: templates = [] } = usePaperStrategyTemplates();
  const create = useCreatePaperStrategy();

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [instruments, setInstruments] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("1d");
  const [product, setProduct] = useState<Product>("CNC");
  const [params, setParams] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const tpl = useMemo(() => templates.find((t) => t.slug === slug) ?? null, [templates, slug]);

  const pick = (s: string) => {
    setSlug(s);
    setErr(null);
    const t = templates.find((x) => x.slug === s);
    if (t) {
      setName(t.name);
      setTimeframe(t.supported_timeframes.includes("1d") ? "1d" : t.supported_timeframes[0] ?? "1d");
      const seed: Record<string, string> = {};
      for (const k of KEY_PARAMS) if (t.params[k]) seed[k] = String(t.params[k].default ?? "");
      setParams(seed);
    }
  };

  const submit = () => {
    setErr(null);
    if (!slug) return setErr("Pick a strategy.");
    if (instruments.length === 0) return setErr("Add at least one instrument.");
    let merged: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === "") continue;
      merged[k] = tpl?.params[k]?.type === "number" || tpl?.params[k]?.type === "integer" ? Number(v) : v;
    }
    if (advanced.trim()) {
      try {
        merged = { ...merged, ...JSON.parse(advanced) };
      } catch {
        return setErr("Advanced overrides must be valid JSON.");
      }
    }
    create.mutate(
      { slug, name, instruments, timeframe, product, params: merged, flatten_on_stop: true },
      {
        onSuccess: () => onDone(),
        onError: (e: unknown) => setErr((e as { message?: string })?.message ?? "Deploy failed."),
      },
    );
  };

  return (
    <SectionCard title="Deploy a strategy into the paper account" bodyClassName="p-3">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs">
          <span className="text-fg-faint">Strategy</span>
          <select
            value={slug}
            onChange={(e) => pick(e.target.value)}
            className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm"
          >
            <option value="">— pick from the library —</option>
            {templates.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name} · {t.category}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-fg-faint">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm"
          />
        </label>
      </div>

      {tpl && (
        <p className="mt-2 text-[11px] text-fg-faint">
          {tpl.description}
          {tpl.warning && <span className="mt-1 block text-amber-500">{tpl.warning}</span>}
          <span className="mt-1 block">
            Needs {tpl.min_instruments}
            {tpl.max_instruments ? `–${tpl.max_instruments}` : "+"} instruments · timeframes{" "}
            {tpl.supported_timeframes.join(", ")}
          </span>
        </p>
      )}

      <div className="mt-3">
        <span className="text-xs text-fg-faint">Instruments</span>
        <InstrumentSearch
          value={instruments}
          onChange={setInstruments}
          multiple
          placeholder="Add stocks / futures / options…"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs">
          <span className="text-fg-faint">Timeframe</span>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="mt-0.5 rounded-md border border-line bg-bg px-2 py-1.5 text-sm"
          >
            {(tpl?.supported_timeframes ?? ["1d"]).map((t) => (
              <option key={t} value={t}>
                {TF_LABEL[t] ?? t}
              </option>
            ))}
          </select>
        </label>
        <div className="text-xs">
          <span className="text-fg-faint">Product</span>
          <div className="mt-0.5 flex gap-1">
            {PRODUCTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setProduct(p)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px] font-medium",
                  product === p ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted",
                )}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tpl && (
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {KEY_PARAMS.filter((k) => tpl.params[k]).map((k) => {
            const spec = tpl.params[k];
            return (
              <label key={k} className="text-xs">
                <span className="text-fg-faint">{k.replace(/_/g, " ")}</span>
                {spec.choices ? (
                  <select
                    value={params[k] ?? ""}
                    onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
                    className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm"
                  >
                    {spec.choices.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={spec.type === "number" || spec.type === "integer" ? "number" : "text"}
                    value={params[k] ?? ""}
                    onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
                    className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm tabular-nums"
                  />
                )}
              </label>
            );
          })}
        </div>
      )}

      <label className="mt-3 block text-xs">
        <span className="text-fg-faint">Advanced overrides (JSON, optional)</span>
        <textarea
          value={advanced}
          onChange={(e) => setAdvanced(e.target.value)}
          placeholder='{"ema_fast": 20, "ema_slow": 50}'
          className="mt-0.5 h-16 w-full rounded-md border border-line bg-bg p-2 font-mono text-[11px]"
        />
      </label>

      {err && <p className="mt-2 rounded bg-neg/10 px-2 py-1.5 text-xs text-neg">{err}</p>}

      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={submit} disabled={create.isPending || !slug}>
          {create.isPending ? "Deploying…" : "Deploy"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-fg-faint">
        The strategy is evaluated on each closed bar and its orders fill through the same paper engine —
        trades appear in your positions / holdings / P&L, tagged to this run. Stopping it squares off
        what it opened.
      </p>
    </SectionCard>
  );
}
