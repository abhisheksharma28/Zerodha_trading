import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { DynamicParamsForm } from "@/components/DynamicParamsForm";
import { schemaErrors } from "@/lib/paramValidation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateStrategyFromTemplate,
  useStrategyTemplate,
} from "@/hooks/useStrategyLibrary";
import type { StrategyTemplateDetail } from "@/types/api";

export default function StrategyTemplateDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const [search] = useSearchParams();
  const { data: t, isLoading } = useStrategyTemplate(slug);
  const [building, setBuilding] = useState(search.get("create") === "1");

  if (isLoading) return <p className="text-sm text-fg-faint">Loading…</p>;
  if (!t) return <p className="text-sm text-fg-faint">Template not found.</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t.name}</h1>
          <div className="flex flex-wrap gap-1.5 pt-2">
            <Badge>{t.category}</Badge>
            <Badge variant="info">{t.time_horizon}</Badge>
            <Badge>{t.timeframe}</Badge>
            <Badge variant={t.complexity === "High" ? "destructive" : "warning"}>
              {t.complexity} complexity
            </Badge>
          </div>
        </div>
        <Button onClick={() => setBuilding((b) => !b)}>
          {building ? "Hide builder" : "Create strategy"}
        </Button>
      </div>

      <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm text-amber-400/90">
        {t.warning} These are educational research templates, not investment advice.
      </p>

      {building && <BuilderPanel template={t} />}

      <Section title="Overview">
        <p className="text-sm text-fg-muted">{t.description}</p>
      </Section>

      <Section title="Logic">
        <p className="text-sm leading-relaxed text-fg-muted">{t.logic}</p>
      </Section>

      <Section title="Risks / failure modes">
        <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
          {t.risks.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </Section>

      <Section title="Best suited for">
        <p className="text-sm text-fg-muted">{t.best_for}</p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {[
            t.supports_intraday && "Intraday",
            t.supports_swing && "Swing",
            t.supports_market_neutral && "Market-neutral",
          ]
            .filter(Boolean)
            .map((x) => (
              <span key={x as string} className="rounded bg-elevated px-1.5 py-0.5">
                {x}
              </span>
            ))}
        </div>
      </Section>

      <Section title="Example">
        <p className="text-sm text-fg-muted">{t.example}</p>
      </Section>

      <Section title="Required data">
        <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
          {t.required_data.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </Section>

      <Section title="Parameters">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-fg-faint">
              <tr>
                <th className="py-1 pr-4">Name</th>
                <th className="py-1 pr-4">Type</th>
                <th className="py-1 pr-4">Default</th>
                <th className="py-1 pr-4">Range</th>
                <th className="py-1">Description</th>
              </tr>
            </thead>
            <tbody className="text-fg-muted">
              {Object.entries(t.parameters).map(([name, spec]) => (
                <tr key={name} className="border-t border-line">
                  <td className="py-1.5 pr-4 font-mono text-[11px]">{name}</td>
                  <td className="py-1.5 pr-4">{spec.type}</td>
                  <td className="py-1.5 pr-4 font-mono text-[11px]">{String(spec.default)}</td>
                  <td className="py-1.5 pr-4">
                    {spec.min != null || spec.max != null
                      ? `${spec.min ?? "-∞"}–${spec.max ?? "∞"}`
                      : spec.choices
                        ? spec.choices.join(" | ")
                        : "—"}
                  </td>
                  <td className="py-1.5 text-fg-muted">{spec.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function BuilderPanel({ template: t }: { template: StrategyTemplateDetail }) {
  const navigate = useNavigate();
  const create = useCreateStrategyFromTemplate(t.slug);
  const presetNames = Object.keys(t.presets);
  const [preset, setPreset] = useState(presetNames.includes("balanced") ? "balanced" : presetNames[0]);
  const [name, setName] = useState(`${t.name} v1`);

  const defaults = useMemo(() => {
    const base: Record<string, unknown> = {};
    for (const [k, spec] of Object.entries(t.parameters)) base[k] = spec.default;
    return { ...base, ...(t.presets[preset] ?? {}) };
  }, [t, preset]);

  const [values, setValues] = useState<Record<string, unknown>>(defaults);
  // reset when preset changes
  const [lastPreset, setLastPreset] = useState(preset);
  if (lastPreset !== preset) {
    setLastPreset(preset);
    setValues(defaults);
  }

  const errors = schemaErrors(t.parameters, values);
  const hasErrors = Object.keys(errors).length > 0;

  return (
    <Card className="border-accent/40">
      <CardHeader>
        <CardTitle>Create a strategy from this template</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="strategy-name">Strategy name</Label>
            <Input id="strategy-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="preset">Research preset (starting point, not a recommendation)</Label>
            <select
              id="preset"
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
            >
              {presetNames.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-xs text-fg-faint">
          Preset parameters are starting points for research and should be validated using
          out-of-sample testing.
        </p>

        <DynamicParamsForm schema={t.parameters} values={values} onChange={setValues} />

        {create.isError && (
          <p className="text-xs text-neg">{(create.error as Error).message}</p>
        )}
        <div>
          <Button
            disabled={create.isPending || hasErrors || !name.trim()}
            onClick={() =>
              create.mutate(
                { name: name.trim(), preset: null, parameters: values },
                { onSuccess: (s) => navigate(`/strategies/${s.id}`) },
              )
            }
          >
            {create.isPending ? "Creating…" : "Create strategy"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
