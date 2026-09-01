import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateStrategy, useStrategies } from "@/hooks/useStrategies";

const DEFAULT_SOURCE = `from app.strategies.base import BaseStrategy


class Strategy(BaseStrategy):
    """Runs unmodified in backtest, simulation, paper, and live modes."""

    def on_bar(self, bar):
        # Access strategy parameters via self.context.parameters and current
        # positions via self.context.positions. Call
        # self.context.submit_order(...) to express trade intent.
        pass
`;

export default function StrategiesPage() {
  const { data: strategies, isLoading } = useStrategies();
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Strategies</h1>
          <p className="text-sm text-neutral-400">
            Each strategy is a stable identity; editing it always creates a new immutable version.
          </p>
        </div>
        <Button onClick={() => setShowForm((s) => !s)}>
          {showForm ? "Cancel" : "New strategy"}
        </Button>
      </div>

      {showForm && <CreateStrategyForm onDone={() => setShowForm(false)} />}

      {isLoading && <p className="text-sm text-neutral-500">Loading…</p>}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {strategies?.map((strategy) => (
          <Link key={strategy.id} to={`/strategies/${strategy.id}`}>
            <Card className="h-full transition-colors hover:border-neutral-700">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{strategy.name}</CardTitle>
                  <Badge variant={strategy.status === "active" ? "success" : "default"}>
                    {strategy.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="line-clamp-2 text-xs text-neutral-500">
                  {strategy.description ?? "No description"}
                </p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {strategies?.length === 0 && !isLoading && (
        <p className="text-sm text-neutral-500">No strategies yet — create one to get started.</p>
      )}
    </div>
  );
}

function CreateStrategyForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceCode, setSourceCode] = useState(DEFAULT_SOURCE);
  const create = useCreateStrategy();

  return (
    <Card>
      <CardHeader>
        <CardTitle>New strategy</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              {
                name,
                description: description || undefined,
                initial_version: { source_code: sourceCode },
              },
              { onSuccess: onDone },
            );
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="source">
              Source code (must define a `Strategy` subclass of BaseStrategy)
            </Label>
            <textarea
              id="source"
              value={sourceCode}
              onChange={(e) => setSourceCode(e.target.value)}
              rows={12}
              className="rounded-md border border-neutral-700 bg-neutral-900 p-3 font-mono text-xs text-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            />
          </div>
          {create.isError && (
            <p className="text-xs text-red-400">{(create.error as Error).message}</p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create strategy"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
