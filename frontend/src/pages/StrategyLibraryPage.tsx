import { useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSeedStrategyLibrary, useStrategyTemplates } from "@/hooks/useStrategyLibrary";
import type { StrategyTemplateSummary } from "@/types/api";

const COMPLEXITY_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  Low: "success",
  Medium: "warning",
  High: "destructive",
};

export default function StrategyLibraryPage() {
  const { data: templates, isLoading } = useStrategyTemplates();
  const seed = useSeedStrategyLibrary();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Strategy Library</h1>
          <p className="max-w-2xl text-sm text-fg-muted">
            Research-backed strategy templates requiring validation, optimization and out-of-sample
            testing. These are established quantitative strategy families with academic and
            institutional precedent — <span className="text-fg-muted">not</span> guaranteed,
            risk-free, or proven profitable.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => seed.mutate()}
          disabled={seed.isPending}
        >
          {seed.isPending ? "Seeding…" : "Seed / repair library"}
        </Button>
      </div>

      {seed.data && (
        <p className="text-xs text-fg-faint">
          Created: {seed.data.created.join(", ") || "none"} · Skipped:{" "}
          {seed.data.skipped.join(", ") || "none"}
        </p>
      )}

      {isLoading && <p className="text-sm text-fg-faint">Loading…</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {templates?.map((t) => <TemplateCard key={t.slug} template={t} />)}
      </div>
    </div>
  );
}

function TemplateCard({ template: t }: { template: StrategyTemplateSummary }) {
  const navigate = useNavigate();
  const caps = [
    t.supports_long && "Long",
    t.supports_short && "Short",
    t.supports_market_neutral && "Market-neutral",
  ].filter(Boolean) as string[];

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base">{t.name}</CardTitle>
          <Badge variant={COMPLEXITY_VARIANT[t.complexity] ?? "default"}>{t.complexity}</Badge>
        </div>
        <div className="flex flex-wrap gap-1.5 pt-1">
          <Badge>{t.category}</Badge>
          <Badge variant="info">{t.time_horizon}</Badge>
          <Badge>{t.timeframe}</Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <p className="text-sm text-fg-muted">{t.description}</p>
        <div className="flex flex-wrap gap-1.5 text-xs text-fg-faint">
          {caps.map((c) => (
            <span key={c} className="rounded bg-elevated px-1.5 py-0.5">
              {c}
            </span>
          ))}
          <span className="rounded bg-elevated px-1.5 py-0.5">
            {t.min_instruments === t.max_instruments
              ? `${t.min_instruments} instrument${t.min_instruments > 1 ? "s" : ""}`
              : `${t.min_instruments}+ instruments`}
          </span>
        </div>
        <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-400/90">
          {t.warning}
        </p>
        <div className="mt-auto flex gap-2 pt-1">
          <Button size="sm" onClick={() => navigate(`/strategy-library/${t.slug}`)}>
            Open
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate(`/strategy-library/${t.slug}?create=1`)}
          >
            Create strategy
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
