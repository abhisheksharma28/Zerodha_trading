import { cn } from "@/lib/utils";
import type { TradingMode } from "@/types/api";

const LABELS: Record<TradingMode, string> = {
  backtest: "Backtest",
  simulation: "Simulation",
  paper: "Paper",
  live: "LIVE",
};

/**
 * The one visual element every deployment/order/log row renders through.
 * LIVE is deliberately the loudest, most different-looking state in the
 * whole UI — see requirement #14: an operator should never be able to
 * mistake a live deployment for anything else at a glance, especially
 * scanning a long list quickly.
 */
export function ModeBadge({ mode, className }: { mode: TradingMode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
        `mode-${mode}`,
        mode === "live" && "animate-pulse",
        className,
      )}
    >
      {mode === "live" && <span className="h-1.5 w-1.5 rounded-full bg-red-500" />}
      {LABELS[mode]}
    </span>
  );
}
