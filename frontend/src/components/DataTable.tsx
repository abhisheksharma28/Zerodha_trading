import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  /** Provide to make the column sortable (click the header) and searchable. */
  sortValue?: (row: T) => string | number | null | undefined;
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty = "Nothing to show yet.",
  searchable = false,
  searchPlaceholder = "Filter…",
  initialSort = null,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  searchable?: boolean;
  searchPlaceholder?: string;
  initialSort?: SortState;
}) {
  const [sort, setSort] = useState<SortState>(initialSort);
  const [query, setQuery] = useState("");

  const alignCls = (a?: string) =>
    a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";

  const searchCols = useMemo(() => columns.filter((c) => c.sortValue), [columns]);

  const view = useMemo(() => {
    let out = rows;
    const q = query.trim().toLowerCase();
    if (q && searchCols.length > 0) {
      out = out.filter((row) =>
        searchCols.some((c) => String(c.sortValue?.(row) ?? "").toLowerCase().includes(q)),
      );
    }
    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      if (col?.sortValue) {
        const dir = sort.dir === "asc" ? 1 : -1;
        out = [...out].sort((a, b) => {
          const av = col.sortValue!(a);
          const bv = col.sortValue!(b);
          if (av == null && bv == null) return 0;
          if (av == null) return 1;
          if (bv == null) return -1;
          if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
          return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
        });
      }
    }
    return out;
  }, [rows, query, sort, columns, searchCols]);

  const cycleSort = (key: string) =>
    setSort((s) =>
      s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null,
    );

  return (
    <div className="flex flex-col gap-2">
      {searchable && searchCols.length > 0 && (
        <div className="flex items-center gap-2 px-3 pt-1">
          <Search className="h-3.5 w-3.5 text-fg-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="h-7 w-full max-w-xs rounded-md border border-line-strong bg-surface px-2 text-xs text-fg placeholder:text-fg-faint"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="text-[11px] text-fg-faint hover:text-fg"
            >
              clear
            </button>
          )}
          <span className="ml-auto text-[11px] text-fg-faint">
            {view.length} of {rows.length}
          </span>
        </div>
      )}

      {view.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-faint">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-[11px] uppercase tracking-wide text-fg-faint">
                {columns.map((c) => {
                  const active = sort?.key === c.key;
                  return (
                    <th
                      key={c.key}
                      className={cn("px-3 py-2 font-medium", alignCls(c.align))}
                    >
                      {c.sortValue ? (
                        <button
                          type="button"
                          onClick={() => cycleSort(c.key)}
                          className={cn(
                            "inline-flex items-center gap-1 hover:text-fg",
                            active && "text-fg",
                            c.align === "right" && "flex-row-reverse",
                          )}
                        >
                          {c.header}
                          {active ? (
                            sort?.dir === "asc" ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : (
                              <ArrowDown className="h-3 w-3" />
                            )
                          ) : (
                            <ChevronsUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      ) : (
                        c.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {view.map((row, i) => (
                <tr
                  key={rowKey(row, i)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-b border-line/70 last:border-0",
                    onRowClick && "cursor-pointer hover:bg-elevated/60",
                  )}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn("px-3 py-2.5 tabular-nums", alignCls(c.align), c.className)}
                    >
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
