import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";

import { useInstrumentSearch } from "@/hooks/useInstruments";
import { cn } from "@/lib/utils";

const RECENT_KEY = "nav-instrument-search.recent";

type Recent = { exchange: string; symbol: string; name?: string | null };

function readRecent(): Recent[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as Recent[];
  } catch {
    return [];
  }
}
function pushRecent(r: Recent) {
  try {
    const next = [
      r,
      ...readRecent().filter((x) => !(x.exchange === r.exchange && x.symbol === r.symbol)),
    ].slice(0, 6);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* recents are a convenience */
  }
}

const TYPE_BADGE: Record<string, string> = {
  EQ: "bg-sky-500/15 text-sky-300",
  FUT: "bg-violet-500/15 text-violet-300",
  CE: "bg-pos/15 text-pos",
  PE: "bg-rose-500/15 text-rose-300",
};

export function NavInstrumentSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const { data: results, isFetching } = useInstrumentSearch(q, { limit: 12 });
  const recent = useMemo(() => (open && !q ? readRecent() : []), [open, q]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- reset highlight when the result set changes
  useEffect(() => setActive(0), [q, results]);

  const go = (exchange: string, symbol: string, name?: string | null) => {
    pushRecent({ exchange, symbol, name });
    setQ("");
    setOpen(false);
    navigate(`/stocks/${exchange}/${encodeURIComponent(symbol)}`);
  };

  const list = results ?? [];

  return (
    <div ref={boxRef} className="relative ml-auto hidden w-64 sm:block">
      <div className="flex items-center gap-2 rounded-md border border-line-strong bg-bg px-2.5 py-1.5 focus-within:border-accent">
        <Search className="h-3.5 w-3.5 shrink-0 text-fg-faint" />
        <input
          value={q}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (!open) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, Math.max(0, list.length - 1)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && list[active]) {
              e.preventDefault();
              go(list[active].exchange, list[active].tradingsymbol, list[active].name);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder="Search instrument…"
          className="h-5 w-full bg-transparent text-xs text-fg outline-none placeholder:text-fg-faint"
        />
      </div>

      {open && (q || recent.length > 0) && (
        <div className="absolute right-0 z-50 mt-1 max-h-80 w-80 overflow-y-auto rounded-lg border border-line-strong bg-surface p-1 shadow-xl">
          {!q && recent.length > 0 && (
            <>
              <p className="px-2 pt-1.5 text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                Recent
              </p>
              {recent.map((r) => (
                <button
                  key={`${r.exchange}:${r.symbol}`}
                  type="button"
                  onClick={() => go(r.exchange, r.symbol, r.name)}
                  className="block w-full rounded px-2 py-1.5 text-left text-sm text-fg-muted hover:bg-elevated"
                >
                  <span className="font-medium text-fg">{r.symbol}</span>
                  {r.name && <span className="ml-2 text-xs text-fg-faint">{r.name}</span>}
                </button>
              ))}
            </>
          )}

          {q && (
            <>
              {isFetching && !results && (
                <p className="px-2 py-2 text-xs text-fg-faint">Searching…</p>
              )}
              {results?.length === 0 && (
                <p className="px-2 py-2 text-xs text-fg-faint">No matches for “{q}”.</p>
              )}
              {list.map((i, idx) => (
                <button
                  key={i.id}
                  type="button"
                  onMouseEnter={() => setActive(idx)}
                  onClick={() => go(i.exchange, i.tradingsymbol, i.name)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left",
                    idx === active ? "bg-elevated" : "hover:bg-elevated",
                  )}
                >
                  <span className="min-w-0">
                    <span className="text-sm text-fg">{i.tradingsymbol}</span>
                    {i.name && (
                      <span className="ml-2 truncate text-xs text-fg-faint">{i.name}</span>
                    )}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 rounded px-1 py-0.5 text-[10px]",
                      TYPE_BADGE[i.instrument_type] ?? "bg-elevated text-fg-muted",
                    )}
                  >
                    {i.exchange} {i.instrument_type}
                  </span>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
