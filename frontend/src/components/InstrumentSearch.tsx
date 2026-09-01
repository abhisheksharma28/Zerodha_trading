import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";

import { instrumentsApi } from "@/api/instruments";
import { useInstrumentSearch, useSyncInstruments } from "@/hooks/useInstruments";
import type { Instrument } from "@/types/api";
import { cn } from "@/lib/utils";

const RECENT_KEY = "instrument-search.recent";
const RECENT_MAX = 8;

function readRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function pushRecent(ref: string) {
  try {
    const next = [ref, ...readRecent().filter((r) => r !== ref)].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — recents are a convenience, not required */
  }
}

function instrumentRef(i: Pick<Instrument, "exchange" | "tradingsymbol">): string {
  return `${i.exchange}:${i.tradingsymbol}`;
}

const TYPE_BADGE: Record<string, string> = {
  EQ: "bg-sky-500/15 text-sky-300",
  FUT: "bg-violet-500/15 text-violet-300",
  CE: "bg-pos/15 text-pos",
  PE: "bg-rose-500/15 text-rose-300",
};

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  multiple?: boolean;
  instrumentType?: string;
  exchange?: string;
  placeholder?: string;
}

export function InstrumentSearch({
  value,
  onChange,
  multiple = true,
  instrumentType,
  exchange,
  placeholder = "Search by symbol, company name or underlying…",
}: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const { data: results, isFetching } = useInstrumentSearch(q, {
    instrument_type: instrumentType,
    exchange,
    limit: 20,
  });
  const sync = useSyncInstruments();
  const recent = useMemo(() => (open && !q ? readRecent() : []), [open, q]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMiss, setBulkMiss] = useState<string[]>([]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function add(ref: string) {
    pushRecent(ref);
    if (!multiple) {
      onChange([ref]);
    } else if (!value.includes(ref)) {
      onChange([...value, ref]);
    }
    setQ("");
    setOpen(multiple);
  }

  function remove(ref: string) {
    onChange(value.filter((r) => r !== ref));
  }

  async function bulkResolve(text: string) {
    if (!multiple) return;
    setBulkBusy(true);
    setBulkMiss([]);
    try {
      const res = await instrumentsApi.resolve([text], exchange ?? "NSE");
      const refs = res.resolved.map((r) => r.ref).filter((r) => !value.includes(r));
      if (refs.length) onChange([...value, ...refs]);
      refs.forEach(pushRecent);
      setBulkMiss(res.unresolved);
      setQ("");
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <div ref={boxRef} className="relative">
      <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 py-1.5 focus-within:border-accent">
        {value.map((ref) => (
          <span
            key={ref}
            className="flex items-center gap-1 rounded bg-elevated px-2 py-0.5 text-xs text-fg"
          >
            {ref}
            <button
              type="button"
              onClick={() => remove(ref)}
              className="text-fg-faint hover:text-fg"
              aria-label={`Remove ${ref}`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <div className="flex min-w-[8rem] flex-1 items-center gap-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-fg-faint" />
          <input
            value={q}
            onChange={(e) => {
              const v = e.target.value;
              setOpen(true);
              if (multiple && /[,\n;]/.test(v)) {
                void bulkResolve(v);
              } else {
                setQ(v);
              }
            }}
            onPaste={(e) => {
              const text = e.clipboardData.getData("text");
              if (multiple && /[,\n;]/.test(text)) {
                e.preventDefault();
                void bulkResolve(text);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && multiple && q.trim() && !results?.length) {
                e.preventDefault();
                void bulkResolve(q);
              }
            }}
            onFocus={() => setOpen(true)}
            placeholder={
              value.length && !multiple
                ? ""
                : multiple
                  ? "Search, or paste a comma-separated list…"
                  : placeholder
            }
            className="h-6 w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-faint"
          />
        </div>
      </div>
      {bulkBusy && <p className="mt-1 text-[11px] text-fg-faint">Resolving instruments…</p>}
      {bulkMiss.length > 0 && (
        <p className="mt-1 text-[11px] text-neg">Not found: {bulkMiss.join(", ")}</p>
      )}

      {open && (
        <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-line-strong bg-surface shadow-xl">
          {!q && recent.length > 0 && (
            <>
              <p className="px-3 pt-2 text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                Recent
              </p>
              {recent.map((ref) => (
                <button
                  key={ref}
                  type="button"
                  onClick={() => add(ref)}
                  className="block w-full px-3 py-1.5 text-left text-sm text-fg-muted hover:bg-elevated"
                >
                  {ref}
                </button>
              ))}
            </>
          )}
          {q && (
            <>
              {isFetching && !results && (
                <p className="px-3 py-2 text-xs text-fg-faint">Searching…</p>
              )}
              {results?.length === 0 && (
                <div className="px-3 py-2 text-xs text-fg-faint">
                  <p>No matches for “{q}”.</p>
                  <button
                    type="button"
                    onClick={() => sync.mutate(undefined)}
                    disabled={sync.isPending}
                    className="mt-1 rounded border border-line-strong px-2 py-1 text-fg-muted hover:bg-elevated disabled:opacity-50"
                  >
                    {sync.isPending
                      ? "Syncing instrument master…"
                      : sync.isSuccess
                        ? "Synced — try again"
                        : "Sync instrument master from Zerodha"}
                  </button>
                  {sync.isError && (
                    <p className="mt-1 text-neg">{(sync.error as Error).message}</p>
                  )}
                </div>
              )}
              {results?.map((i) => {
                const ref = instrumentRef(i);
                const selected = value.includes(ref);
                return (
                  <button
                    key={i.id}
                    type="button"
                    disabled={selected}
                    onClick={() => add(ref)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-elevated",
                      selected && "opacity-40",
                    )}
                  >
                    <span className="min-w-0">
                      <span className="text-sm text-fg">{i.tradingsymbol}</span>
                      {i.name && (
                        <span className="ml-2 truncate text-xs text-fg-faint">{i.name}</span>
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5 text-[10px] text-fg-faint">
                      {i.expiry && <span>{i.expiry}</span>}
                      <span
                        className={cn(
                          "rounded px-1 py-0.5",
                          TYPE_BADGE[i.instrument_type] ?? "bg-elevated text-fg-muted",
                        )}
                      >
                        {i.exchange} {i.instrument_type}
                      </span>
                    </span>
                  </button>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}
