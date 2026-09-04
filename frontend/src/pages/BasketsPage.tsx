import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDownUp, Layers, Loader2, Plus, Search, X } from "lucide-react";

import type { BasketSpec, BasketTemplate, Frequency, Sleeve } from "@/api/baskets";
import { basketsApi } from "@/api/baskets";
import { SleeveEditor, emptySleeve } from "@/components/baskets/SleeveEditor";
import { PageHeader } from "@/components/PageHeader";
import { Sparkline } from "@/components/Sparkline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBasketTemplates, useBaskets, useCreateBasket } from "@/hooks/useBaskets";
import { inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const FREQS: Frequency[] = ["weekly", "monthly", "quarterly"];

// sort/filter applies to the flagship product catalog
type SortKey = "default" | "name" | "risk" | "cagr" | "excess" | "sharpe" | "maxdd" | "minfunds";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "default", label: "By investing goal" },
  { key: "risk", label: "Risk level (low → high)" },
  { key: "cagr", label: "CAGR (high → low)" },
  { key: "excess", label: "vs benchmark (high → low)" },
  { key: "sharpe", label: "Sharpe (high → low)" },
  { key: "maxdd", label: "Max drawdown (smallest)" },
  { key: "minfunds", label: "Min. investment (low → high)" },
  { key: "name", label: "Name (A–Z)" },
];

const num0 = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? Number.NEGATIVE_INFINITY : v;

const RISK_TONE: Record<number, string> = {
  1: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600",
  2: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600",
  3: "border-amber-400/40 bg-amber-400/10 text-amber-600",
  4: "border-orange-500/40 bg-orange-500/10 text-orange-600",
  5: "border-rose-500/40 bg-rose-500/10 text-rose-600",
};

function specForPayload(sleeves: Sleeve[]): BasketSpec {
  return {
    sleeves: sleeves.map((sl) => ({
      ...sl,
      members: sl.members.map((m) => (m.includes(":") ? m.split(":")[1] : m).toUpperCase()),
    })),
  };
}

export default function BasketsPage() {
  const nav = useNavigate();
  const { data: baskets, isLoading } = useBaskets();
  const { data: catalog } = useBasketTemplates();
  const create = useCreateBasket();

  const [query, setQuery] = useState("");
  const [catFilter, setCatFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("default");

  const [open, setOpen] = useState(false);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [benchmark, setBenchmark] = useState("NIFTY 50");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [driftBand, setDriftBand] = useState(3);
  const [capital, setCapital] = useState(500_000);
  const [sleeves, setSleeves] = useState<Sleeve[]>([emptySleeve(1)]);
  const [error, setError] = useState<string | null>(null);
  // product metadata carried through from a cloned flagship (no form fields)
  const [tplMeta, setTplMeta] = useState<{
    risk_level?: number;
    objective?: string;
    horizon?: string;
    investment_style?: string;
    how_it_works?: string[];
  }>({});

  const total = sleeves.reduce((s, sl) => s + (Number(sl.weight_pct) || 0), 0);
  const canSubmit =
    name.trim().length > 0 &&
    Math.abs(total - 100) < 0.5 &&
    sleeves.every((sl) => sl.members.length > 0);

  const resetForm = () => {
    setTemplateName(null);
    setName("");
    setDescription("");
    setCategory("");
    setBenchmark("NIFTY 50");
    setFrequency("monthly");
    setDriftBand(3);
    setCapital(500_000);
    setSleeves([emptySleeve(1)]);
    setTplMeta({});
    setError(null);
  };

  const applyTemplate = (key: string) => {
    const t =
      catalog?.templates.find((x) => x.key === key) ??
      catalog?.internal_models?.find((x) => x.key === key);
    if (!t) return;
    setOpen(true);
    setTemplateName(t.name);
    setName(t.name);
    setDescription(t.objective ?? t.description);
    setCategory(t.category);
    setBenchmark(t.benchmark);
    setFrequency(t.rebalance_frequency);
    setDriftBand(t.drift_band_pct ?? 3);
    setSleeves(
      t.spec.sleeves.map((sl) => ({
        ...sl,
        members: sl.members.map((m) => (m.includes(":") ? m : `NSE:${m}`)),
      })),
    );
    setTplMeta({
      risk_level: t.risk_level,
      objective: t.objective,
      horizon: t.horizon,
      investment_style: t.investment_style,
      how_it_works: t.how_it_works,
    });
    setError(null);
  };

  // create -> backtest -> open the detail page, in one action
  const submit = async () => {
    setError(null);
    try {
      const b = await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        category: category || undefined,
        risk_level: tplMeta.risk_level,
        objective: tplMeta.objective,
        horizon: tplMeta.horizon,
        investment_style: tplMeta.investment_style,
        how_it_works: tplMeta.how_it_works,
        benchmark,
        rebalance_frequency: frequency,
        drift_band_pct: driftBand,
        capital,
        spec: specForPayload(sleeves),
      });
      basketsApi.backtest(b.id, 5).catch(() => undefined); // fire-and-forget warm-up
      resetForm();
      setOpen(false);
      nav(`/baskets/${b.id}`);
    } catch (e) {
      const msg =
        (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data
          ?.message ??
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not create the basket.";
      setError(String(msg));
    }
  };

  // "Your baskets" — just newest-first; the filter/sort controls belong to the
  // template catalog below, which is the long list that needs them.
  const myBaskets = useMemo(() => {
    const list = [...(baskets ?? [])];
    list.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    return list;
  }, [baskets]);

  const grouped = sortKey === "default" && !query.trim() && catFilter === "all";

  const templates = useMemo(() => {
    const all = catalog?.templates ?? [];
    const q = query.trim().toLowerCase();
    const filtered = all.filter((t) => {
      if (catFilter !== "all" && t.category !== catFilter) return false;
      if (!q) return true;
      const hay = [
        t.name,
        t.objective ?? t.description,
        t.category,
        t.investment_style ?? "",
        ...(t.tags ?? []),
        ...t.spec.sleeves.flatMap((s) => s.members),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
    if (sortKey === "default") return filtered;
    const m = (t: BasketTemplate) => t.backtest?.metrics ?? {};
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "name":
          return a.name.localeCompare(b.name);
        case "risk":
          return (a.risk_level ?? 9) - (b.risk_level ?? 9) || a.name.localeCompare(b.name);
        case "cagr":
          return num0(m(b).cagr_pct) - num0(m(a).cagr_pct);
        case "excess":
          return num0(m(b).excess_return_pct) - num0(m(a).excess_return_pct);
        case "sharpe":
          return num0(m(b).sharpe_ratio) - num0(m(a).sharpe_ratio);
        case "maxdd": // smallest drawdown magnitude first (values are negative %)
          return num0(m(b).max_drawdown_pct) - num0(m(a).max_drawdown_pct);
        case "minfunds":
          return (
            (a.min_funds?.unit_cost ?? Number.POSITIVE_INFINITY) -
            (b.min_funds?.unit_cost ?? Number.POSITIVE_INFINITY)
          );
        default:
          return 0;
      }
    });
  }, [catalog, query, catFilter, sortKey]);

  const journeyGroups = useMemo(() => {
    const byKey = new Map(templates.map((t) => [t.key, t]));
    const j = catalog?.journeys ?? {};
    return Object.entries(j)
      .map(([label, keys]) => ({
        label,
        items: keys.map((k) => byKey.get(k)).filter(Boolean) as BasketTemplate[],
      }))
      .filter((g) => g.items.length > 0);
  }, [catalog, templates]);

  const clearTemplateFilters = () => {
    setQuery("");
    setCatFilter("all");
    setSortKey("default");
  };

  const closeForm = () => {
    resetForm();
    setOpen(false);
  };

  // esc-to-close + lock the page scroll while the modal is up
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeForm();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Baskets"
        subtitle="Smallcase-style portfolios — fixed-weight sleeves with an optional rotation rule, rebalanced on a schedule and deployable to the paper account."
        actions={
          <Button
            size="sm"
            onClick={() => {
              if (open) closeForm();
              else {
                resetForm();
                setOpen(true);
              }
            }}
          >
            <Plus className="mr-1 h-4 w-4" /> New basket
          </Button>
        }
      />

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 backdrop-blur-sm sm:p-8"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeForm();
          }}
        >
          <div className="my-auto w-full max-w-3xl rounded-lg border border-line-strong bg-surface shadow-2xl">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <p className="font-display text-sm font-semibold text-fg">New basket</p>
                {templateName && (
                  <p className="text-[11px] text-accent">
                    Loaded from “{templateName}” — review &amp; adjust below
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={closeForm}
                className="rounded-md p-1 text-fg-muted hover:bg-elevated"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          <div className="flex max-h-[80vh] flex-col gap-4 overflow-y-auto p-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="All-Weather" />
              </Field>
              <Field label="Benchmark">
                <Input value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
              </Field>
              <Field label="Description">
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="optional"
                />
              </Field>
              <Field label="Category">
                <select
                  className="h-9 w-full rounded-md border border-line bg-surface px-2 text-sm"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="">— none —</option>
                  {(catalog?.categories ?? []).map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Rebalance">
                <select
                  className="h-9 w-full rounded-md border border-line bg-surface px-2 text-sm"
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value as Frequency)}
                >
                  {FREQS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Drift band %">
                <Input
                  type="number"
                  value={driftBand}
                  onChange={(e) => setDriftBand(Number(e.target.value))}
                />
              </Field>
              <Field label="Capital (₹)">
                <Input
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value))}
                />
              </Field>
            </div>

            <SleeveEditor sleeves={sleeves} onChange={setSleeves} />

            {error && <p className="text-sm text-neg">{error}</p>}

            <div className="flex items-center gap-2">
              <Button disabled={!canSubmit || create.isPending} onClick={submit}>
                {create.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                Create &amp; backtest
              </Button>
              <Button variant="ghost" onClick={closeForm}>
                Cancel
              </Button>
              {!canSubmit && (
                <span className="text-xs text-fg-faint">
                  Need a name, sleeves summing to 100%, and at least one member per sleeve.
                </span>
              )}
            </div>
          </div>
          </div>
        </div>
      )}

      <section>
        <div className="mb-2 flex items-baseline gap-1.5">
          <h2 className="text-sm font-semibold text-fg">Your baskets</h2>
          {myBaskets.length > 0 && (
            <span className="text-[11px] font-normal text-fg-faint">({myBaskets.length})</span>
          )}
        </div>
        {isLoading ? (
          <p className="py-8 text-center text-sm text-fg-faint">Loading…</p>
        ) : myBaskets.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line py-8 text-center text-sm text-fg-faint">
            No baskets yet. Create one, or start from a template below.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {myBaskets.map((b) => {
              const s = b.backtest_summary;
              return (
                <button
                  key={b.id}
                  onClick={() => nav(`/baskets/${b.id}`)}
                  className="flex flex-col rounded-lg border border-line bg-surface p-3 text-left transition-colors hover:border-line-strong"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-fg">{b.name}</p>
                      <p className="text-[11px] text-fg-faint">
                        {b.category ? `${b.category} · ` : ""}
                        {b.n_sleeves} sleeves · {b.rebalance_frequency} · {inrCompact(b.capital)}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold capitalize",
                        b.status === "deployed"
                          ? "border-pos/40 bg-pos/10 text-pos"
                          : b.status === "archived"
                            ? "border-line text-fg-faint"
                            : "border-amber-400/40 bg-amber-400/10 text-amber-500",
                      )}
                    >
                      {b.status}
                    </span>
                  </div>

                  <div className="mt-2 flex items-center gap-1 text-[11px] text-fg-muted">
                    <Layers className="h-3.5 w-3.5 text-fg-faint" />
                    {b.sleeves.map((sl) => sl.name).join(" · ")}
                  </div>

                  {s ? (
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <Mini label={`CAGR ${s.years ?? "?"}y`} value={s.cagr_pct} suffix="%" signed />
                      <Mini label="vs bench" value={s.excess_return_pct} suffix=" pts" signed />
                      <Mini label="Sharpe" value={s.sharpe_ratio} digits={2} />
                    </div>
                  ) : (
                    <p className="mt-2 text-[11px] text-fg-faint">Not backtested yet.</p>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {catalog && catalog.templates.length > 0 && (
        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold text-fg">
                Choose an investment product
                <span className="ml-1.5 text-[11px] font-normal text-fg-faint">
                  {templates.length === catalog.templates.length
                    ? `(${catalog.templates.length})`
                    : `(${templates.length} of ${catalog.templates.length})`}
                </span>
              </h2>
              {catalog.backtests_generated_at && (
                <span className="text-[10px] text-fg-faint">
                  Backtested {new Date(catalog.backtests_generated_at).toLocaleDateString("en-IN")} ·
                  costs &amp; slippage included · past results don&apos;t predict the future
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-faint" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter by name, style, stock…"
                  className="h-8 w-56 rounded-md border border-line bg-surface pl-7 pr-2 text-xs placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                />
              </div>
              <select
                className="h-8 rounded-md border border-line bg-surface px-2 text-xs"
                value={catFilter}
                onChange={(e) => setCatFilter(e.target.value)}
              >
                <option value="all">All categories</option>
                {catalog.categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <ArrowDownUp className="h-3.5 w-3.5 text-fg-faint" />
                <select
                  className="h-8 rounded-md border border-line bg-surface px-2 text-xs"
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                >
                  {SORTS.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              {(query.trim() || catFilter !== "all" || sortKey !== "default") && (
                <button
                  className="text-[11px] text-accent hover:underline"
                  onClick={clearTemplateFilters}
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {templates.length === 0 ? (
            <p className="rounded-lg border border-dashed border-line py-8 text-center text-sm text-fg-faint">
              No products match those filters.{" "}
              <button className="text-accent hover:underline" onClick={clearTemplateFilters}>
                Clear
              </button>
            </p>
          ) : grouped ? (
            journeyGroups.map((g) => (
              <div key={g.label}>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                  {g.label}
                </p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {g.items.map((t) => (
                    <TemplateCard
                      key={t.key}
                      t={t}
                      riskLabel={catalog.risk_labels[String(t.risk_level ?? "")]}
                      onUse={() => applyTemplate(t.key)}
                    />
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {templates.map((t) => (
                <TemplateCard
                  key={t.key}
                  t={t}
                  riskLabel={catalog.risk_labels[String(t.risk_level ?? "")]}
                  onUse={() => applyTemplate(t.key)}
                />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function TemplateCard({
  t,
  riskLabel,
  onUse,
}: {
  t: BasketTemplate;
  riskLabel?: string;
  onUse: () => void;
}) {
  const [showHow, setShowHow] = useState(false);
  const bt = t.backtest;
  const m = bt?.metrics ?? {};
  const oos = bt?.oos?.out_of_sample ?? {};
  const sgn = (v: number | null | undefined, d = 1) =>
    v == null ? "–" : `${v >= 0 ? "+" : ""}${num(v, d)}`;
  const meta = [t.horizon, t.investment_style, t.holdings, `${t.rebalance_frequency} rebalance`].filter(
    Boolean,
  );

  return (
    <div className="flex flex-col rounded-lg border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg">{t.name}</p>
          <p className="text-[10px] uppercase tracking-wide text-fg-faint">{t.category}</p>
        </div>
        {t.risk_level != null && (
          <span
            className={cn(
              "shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold",
              RISK_TONE[t.risk_level] ?? "border-line text-fg-muted",
            )}
            title={`Risk level ${t.risk_level} of 5`}
          >
            L{t.risk_level}
            {riskLabel ? ` · ${riskLabel}` : ""}
          </span>
        )}
      </div>

      <p className="mt-1.5 flex-1 text-[11px] leading-snug text-fg-muted">
        {t.objective ?? t.description}
      </p>

      {meta.length > 0 && (
        <p className="mt-1.5 text-[10px] text-fg-faint">{meta.join(" · ")}</p>
      )}

      {bt && (
        <div className="mt-2 rounded-md border border-line/70 bg-bg/40 p-2">
          <div className="flex items-center justify-between text-[9px] uppercase tracking-wide text-fg-faint">
            <span>Backtest · {bt.years ?? "?"}y to {bt.end?.slice(0, 7) ?? ""}</span>
            <span>vs {bt.benchmark}</span>
          </div>
          <div className="mt-1 grid grid-cols-4 gap-1.5 text-center">
            <TMetric label="CAGR" value={`${sgn(m.cagr_pct)}%`} tone={(m.cagr_pct ?? 0) >= 0} />
            <TMetric
              label="vs bench"
              value={`${sgn(m.excess_return_pct)}`}
              tone={(m.excess_return_pct ?? 0) >= 0}
            />
            <TMetric label="Sharpe" value={num(m.sharpe_ratio, 2)} />
            <TMetric label="Max DD" value={`${num(Math.abs(m.max_drawdown_pct ?? 0), 0)}%`} tone={false} />
          </div>
          {bt.spark.length > 3 && (
            <div className="mt-1.5 h-6 w-full">
              <Sparkline data={bt.spark} tone={(m.cagr_pct ?? 0) < 0 ? "neg" : "accent"} />
            </div>
          )}
          {oos.return_pct != null && (
            <p className="mt-1 text-[9px] text-fg-faint">
              Out-of-sample (last {oos.start ? `from ${String(oos.start).slice(0, 7)}` : "third"}):{" "}
              <span className={cn("tabular-nums", Number(oos.return_pct) < 0 ? "text-neg" : "text-pos")}>
                {sgn(Number(oos.return_pct))}%
              </span>{" "}
              vs bench {sgn(Number(oos.benchmark_return_pct))}%
            </p>
          )}
        </div>
      )}

      {(t.how_it_works?.length || t.differentiators?.length) && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowHow((v) => !v)}
            className="text-[11px] font-medium text-accent hover:underline"
          >
            {showHow ? "Hide" : "How it works"}
          </button>
          {showHow && (
            <div className="mt-1 space-y-1.5">
              {t.differentiators && t.differentiators.length > 0 && (
                <ul className="space-y-0.5 text-[11px] text-fg-muted">
                  {t.differentiators.map((d, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-accent" />
                      {d}
                    </li>
                  ))}
                </ul>
              )}
              {t.how_it_works && t.how_it_works.length > 0 && (
                <ul className="space-y-0.5 text-[10px] text-fg-faint">
                  {t.how_it_works.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {t.min_funds && t.min_funds.unit_cost > 0 && (
        <p className="mt-2 text-[10px] text-fg-faint">
          Min. investment{" "}
          <span className="font-semibold text-fg-muted">{inrCompact(t.min_funds.unit_cost)}</span>
          {t.min_funds.est_holdings ? ` — ~${t.min_funds.est_holdings} holdings` : ""}. Size up in
          multiples when deploying.
        </p>
      )}

      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] text-fg-faint">
          {t.spec.sleeves.length} sleeve{t.spec.sleeves.length === 1 ? "" : "s"} · vs {t.benchmark}
        </span>
        <Button size="sm" variant="outline" onClick={onUse}>
          Use
        </Button>
      </div>
    </div>
  );
}

function TMetric({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="text-[8px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "tabular-nums text-[11px] font-semibold",
          tone == null ? "text-fg" : tone ? "text-pos" : "text-neg",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      {children}
    </label>
  );
}

function Mini({
  label,
  value,
  suffix = "",
  digits = 1,
  signed = false,
}: {
  label: string;
  value: number | null | undefined;
  suffix?: string;
  digits?: number;
  signed?: boolean;
}) {
  const has = value != null && Number.isFinite(value);
  const v = value as number;
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wide text-fg-faint">{label}</span>
      <span
        className={cn(
          "tabular-nums font-semibold",
          has && signed ? (v < 0 ? "text-neg" : "text-pos") : "text-fg",
        )}
      >
        {!has ? "–" : signed ? `${v >= 0 ? "+" : ""}${num(v, digits)}${suffix}` : `${num(v, digits)}${suffix}`}
      </span>
    </div>
  );
}
