import { useState } from "react";
import { useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAddStrategyVersion, useStrategy } from "@/hooks/useStrategies";

export default function StrategyDetailPage() {
  const { strategyId } = useParams<{ strategyId: string }>();
  const { data: strategy, isLoading } = useStrategy(strategyId);
  const [editingSource, setEditingSource] = useState<string | null>(null);
  const addVersion = useAddStrategyVersion(strategyId ?? "");

  if (isLoading) return <p className="text-sm text-fg-faint">Loading…</p>;
  if (!strategy) return <p className="text-sm text-fg-faint">Strategy not found.</p>;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">{strategy.name}</h1>
        <p className="text-sm text-fg-muted">{strategy.description}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Versions</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {[...strategy.versions].reverse().map((version) => (
            <div key={version.id} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">v{version.version_number}</span>
                  {strategy.current_version_id === version.id && (
                    <Badge variant="success">current</Badge>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setEditingSource(editingSource === version.id ? null : version.source_code)
                  }
                >
                  {editingSource === version.source_code ? "Hide source" : "View source"}
                </Button>
              </div>
              {version.change_summary && (
                <p className="mt-1 text-xs text-fg-faint">{version.change_summary}</p>
              )}
              {editingSource === version.source_code && (
                <pre className="mt-2 max-h-64 overflow-auto rounded bg-bg p-3 text-xs text-fg-muted">
                  {version.source_code}
                </pre>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <NewVersionForm
        currentSource={strategy.versions.at(-1)?.source_code ?? ""}
        onSubmit={(source, summary) =>
          addVersion.mutate({ source_code: source, change_summary: summary })
        }
        isPending={addVersion.isPending}
        error={addVersion.error as Error | null}
      />
    </div>
  );
}

function NewVersionForm({
  currentSource,
  onSubmit,
  isPending,
  error,
}: {
  currentSource: string;
  onSubmit: (source: string, summary: string) => void;
  isPending: boolean;
  error: Error | null;
}) {
  const [source, setSource] = useState(currentSource);
  const [summary, setSummary] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add new version</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(source, summary);
          }}
        >
          <textarea
            value={source}
            onChange={(e) => setSource(e.target.value)}
            rows={10}
            className="rounded-md border border-line-strong bg-surface p-3 font-mono text-xs text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          />
          <input
            placeholder="What changed and why?"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          />
          {error && <p className="text-xs text-red-400">{error.message}</p>}
          <div>
            <Button type="submit" disabled={isPending}>
              {isPending ? "Saving…" : "Save as new version"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
