import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Layers, Loader2, Plus } from "lucide-react";

import type { BasketSpec, Frequency, Sleeve } from "@/api/baskets";
import { basketsApi } from "@/api/baskets";
import { SleeveEditor, emptySleeve } from "@/components/baskets/SleeveEditor";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBasketTemplates, useBaskets, useCreateBasket } from "@/hooks/useBaskets";
import { inrCompact, num } from "@/lib/format";
import { cn } from "@/lib/utils";

const FREQS: Frequency[] = ["weekly", "monthly", "quarterly"];

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

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [benchmark, setBenchmark] = useState("NIFTY 50");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [driftBand, setDriftBand] = useState(3);
  const [capital, setCapital] = useState(500_000);
  const [sleeves, setSleeves] = useState<Sleeve[]>([emptySleeve(1)]);
  const [error, setError] = useState<string | null>(null);

  const total = sleeves.reduce((s, sl) => s + (Number(sl.weight_pct) || 0), 0);
  const canSubmit =
    name.trim().length > 0 &&
    Math.abs(total - 100) < 0.5 &&
    sleeves.every((sl) => sl.members.length > 0);

  const resetForm = () => {
    setName("");
    setDescription("");
    setCategory("");
    setBenchmark("NIFTY 50");
    setFrequency("monthly");
    setDriftBand(3);
    setCapital(500_000);
    setSleeves([emptySleeve(1)]);
    setError(null);
  };

  const applyTemplate = (key: string) => {
    const t = catalog?.templates.find((x) => x.key === key);
    if (!t) return;
    setOpen(true);
    setName(t.name);
    setDescription(t.description);
    setCategory(t.category);
    setBenchmark(t.benchmark);
    setFrequency(t.rebalance_frequency);
    setDriftBand(t.drift_band_pct);
    setSleeves(
      t.spec.sleeves.map((sl) => ({
        ...sl,
        members: sl.members.map((m) => (m.includes(":") ? m : `NSE:${m}`)),
      })),
    );
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

  const rows = useMemo(() => baskets ?? [], [baskets]);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Baskets"
        subtitle="Smallcase-style portfolios — fixed-weight sleeves with an optional rotation rule, rebalanced on a schedule and deployable to the paper account."
        actions={
          <Button size="sm" onClick={() => setOpen((o) => !o)}>
            <Plus className="mr-1 h-4 w-4" /> New basket
          </Button>
        }
      />

      {open && (
        <SectionCard title="New basket" index={1}>
          <div className="flex flex-col gap-4 p-4">
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
              <Button
                variant="ghost"
                onClick={() => {
                  resetForm();
                  setOpen(false);
                }}
              >
                Cancel
              </Button>
              {!canSubmit && (
                <span className="text-xs text-fg-faint">
                  Need a name, sleeves summing to 100%, and at least one member per sleeve.
                </span>
              )}
            </div>
          </div>
        </SectionCard>
      )}

      {catalog && catalog.templates.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-fg">Start from a template</h2>
          {catalog.categories.map((cat) => {
            const items = catalog.templates.filter((t) => t.category === cat);
            if (items.length === 0) return null;
            return (
              <div key={cat}>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                  {cat}
                </p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {items.map((t) => (
                    <div
                      key={t.key}
                      className="flex flex-col rounded-lg border border-line bg-surface p-3"
                    >
                      <p className="text-sm font-semibold text-fg">{t.name}</p>
                      <p className="mt-1 flex-1 text-[11px] leading-snug text-fg-muted">
                        {t.description}
                      </p>
                      {t.tags?.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {t.tags.slice(0, 4).map((tag) => (
                            <span
                              key={tag}
                              className="rounded bg-elevated px-1.5 py-0.5 text-[9px] text-fg-faint"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="mt-2 flex items-center justify-between">
                        <span className="text-[10px] text-fg-faint">
                          {t.spec.sleeves.length} sleeves · {t.rebalance_frequency}
                        </span>
                        <Button size="sm" variant="outline" onClick={() => applyTemplate(t.key)}>
                          Use
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-fg">Your baskets</h2>
        {isLoading ? (
          <p className="py-8 text-center text-sm text-fg-faint">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line py-8 text-center text-sm text-fg-faint">
            No baskets yet. Create one, or start from a template above.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((b) => {
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
