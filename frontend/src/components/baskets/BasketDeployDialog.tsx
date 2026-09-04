import { useEffect, useState } from "react";
import { Loader2, Minus, Plus, X } from "lucide-react";

import type { RebalanceResult } from "@/api/baskets";
import { basketsApi } from "@/api/baskets";
import { Button } from "@/components/ui/button";
import { useDeployPreview } from "@/hooks/useBaskets";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Size a basket by "units" — whole multiples of one share of every member —
 * and deploy it into the paper account at that capital. */
export function BasketDeployDialog({
  basketId,
  basketName,
  onClose,
  onDeployed,
}: {
  basketId: string;
  basketName: string;
  onClose: () => void;
  onDeployed?: (r: RebalanceResult) => void;
}) {
  const { data: preview, isLoading, isError } = useDeployPreview(basketId);
  // `units` is null until the user picks; the effective value falls back to the
  // server's affordability-aware suggestion, so we never setState from an effect.
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const units = picked ?? Math.max(1, preview?.suggested_units ?? 1);
  const setUnits = (n: number | ((u: number) => number)) =>
    setPicked((cur) => {
      const base = cur ?? units;
      return Math.max(1, Math.floor(typeof n === "function" ? n(base) : n));
    });

  const unitCost = preview?.unit_cost ?? 0;
  const capital = Math.round(unitCost * units);
  const cash = preview?.available_cash ?? 0;
  const maxUnits = preview?.max_units ?? 0;
  const affordable = unitCost > 0 && capital <= cash + 1;

  const deploy = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await basketsApi.deploy(basketId, capital);
      onDeployed?.(r);
      onClose();
    } catch (e) {
      setErr(
        (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data
          ?.message ??
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Deploy failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-md rounded-lg border border-line-strong bg-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div>
            <p className="font-display text-sm font-semibold text-fg">Deploy “{basketName}”</p>
            <p className="text-[11px] text-fg-faint">to the paper account</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-fg-muted hover:bg-elevated"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4 p-4">
          {isLoading ? (
            <p className="py-6 text-center text-sm text-fg-faint">
              <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Pricing the basket…
            </p>
          ) : isError || !preview ? (
            <p className="text-sm text-neg">
              Could not price the basket right now. Close this and try again shortly.
            </p>
          ) : (
            <>
              <div className="rounded-md border border-line/70 bg-bg/40 p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-fg-faint">
                    One share of each · {preview.n_priced}/{preview.n_members} priced
                  </span>
                  <span className="tabular-nums font-semibold text-fg">{inr(unitCost)}</span>
                </div>
                {preview.missing.length > 0 && (
                  <p className="mt-1 text-[10px] text-amber-500">
                    No live price for {preview.missing.join(", ")} — this estimate leaves them out.
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <span className="text-[10px] uppercase tracking-wide text-fg-faint">
                  Units — whole multiples of the basket
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="grid h-9 w-9 place-items-center rounded-md border border-line text-fg-muted hover:bg-elevated disabled:opacity-40"
                    disabled={units <= 1}
                    onClick={() => setUnits((u) => Math.max(1, u - 1))}
                  >
                    <Minus className="h-4 w-4" />
                  </button>
                  <input
                    type="number"
                    min={1}
                    value={units}
                    onChange={(e) =>
                      setUnits(Math.max(1, Math.floor(Number(e.target.value) || 1)))
                    }
                    className="h-9 w-20 rounded-md border border-line bg-surface text-center text-sm tabular-nums focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                  />
                  <button
                    type="button"
                    className="grid h-9 w-9 place-items-center rounded-md border border-line text-fg-muted hover:bg-elevated"
                    onClick={() => setUnits((u) => u + 1)}
                  >
                    <Plus className="h-4 w-4" />
                  </button>
                  {maxUnits > 0 && (
                    <button
                      type="button"
                      className="ml-1 text-[11px] text-accent hover:underline"
                      onClick={() => setUnits(maxUnits)}
                    >
                      max {maxUnits}
                    </button>
                  )}
                </div>
              </div>

              <div className="flex items-end justify-between rounded-md bg-elevated/60 p-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-fg-faint">Deploy size</p>
                  <p className="tabular-nums text-lg font-semibold text-fg">{inr(capital)}</p>
                  <p className="text-[10px] text-fg-faint">
                    {units} × {inr(unitCost)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] uppercase tracking-wide text-fg-faint">Free cash</p>
                  <p
                    className={cn(
                      "tabular-nums text-sm font-semibold",
                      affordable ? "text-fg" : "text-neg",
                    )}
                  >
                    {inr(cash)}
                  </p>
                </div>
              </div>

              <p className="text-[11px] leading-snug text-fg-faint">
                The basket buys {inr(capital)} of stock now and rebalances on its schedule.
                Capital is split across the sleeves by their weights, not one share each.
              </p>

              {!affordable && unitCost > 0 && (
                <p className="text-xs text-neg">
                  {inr(capital)} is more than the {inr(cash)} free in the paper account. Lower the
                  units{maxUnits > 0 ? ` (max ${maxUnits})` : ""} or reset the account first.
                </p>
              )}
              {err && <p className="text-xs text-neg">{err}</p>}

              <div className="flex items-center gap-2">
                <Button disabled={busy || !affordable} onClick={deploy}>
                  {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                  Deploy &amp; buy — {inr(capital)}
                </Button>
                <Button variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
