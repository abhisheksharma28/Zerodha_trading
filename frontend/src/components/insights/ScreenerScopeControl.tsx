import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";

import type { ScreenerScopeOption } from "@/api/screener";
import { useRunScreenerSweep, useScreenerStatus } from "@/hooks/useScreener";
import { cn } from "@/lib/utils";

/** Scope picker + "Re-run screen" for both screener panels. Kicks a
 *  background sweep, polls status while it runs, and refetches the
 *  ratings once it finishes. */
export function ScreenerScopeControl({
  scope,
  scopes,
  sweeping,
}: {
  scope: string;
  scopes: ScreenerScopeOption[];
  sweeping: boolean;
}) {
  const qc = useQueryClient();
  const [choice, setChoice] = useState(scope);
  const run = useRunScreenerSweep();
  const { data: status } = useScreenerStatus(sweeping || run.isPending);
  const isSweeping = sweeping || run.isPending || !!status?.sweeping;
  const wasSweeping = useRef(isSweeping);

  // keep the dropdown in step with the last actual sweep when idle
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync with the server's current scope
    if (!isSweeping) setChoice(scope);
  }, [scope, isSweeping]);

  // when a sweep finishes, pull the fresh ratings in
  useEffect(() => {
    if (wasSweeping.current && !isSweeping) {
      qc.invalidateQueries({ queryKey: ["screener"] });
    }
    wasSweeping.current = isSweeping;
  }, [isSweeping, qc]);

  const opt = scopes.find((s) => s.key === choice);
  const running = isSweeping;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-1.5 text-xs text-fg-muted">
        <span className="text-fg-faint">Scope</span>
        <select
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          disabled={running}
          className="h-8 rounded-md border border-line bg-surface px-2 text-xs disabled:opacity-60"
        >
          {scopes.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={() => run.mutate(choice)}
        disabled={running || choice === scope}
        className={cn(
          "flex h-8 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-xs font-medium",
          running ? "text-fg-faint" : "text-fg-muted hover:bg-elevated hover:text-fg",
          choice === scope && !running && "opacity-50",
        )}
        title={choice === scope ? "This scope is already the current screen" : "Run a fresh sweep"}
      >
        {running ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Sweeping…
          </>
        ) : (
          <>
            <RefreshCw className="h-3.5 w-3.5" /> Re-run screen
          </>
        )}
      </button>
      {running && (
        <span className="text-[11px] text-fg-faint">
          Scanning {opt?.label ?? choice}. {choice === "all" && "This takes ~15–20 min. "}Results
          refresh automatically.
        </span>
      )}
      {!running && run.data && run.data.ok === false && (
        <span className="text-[11px] text-neg">{run.data.reason}</span>
      )}
    </div>
  );
}
