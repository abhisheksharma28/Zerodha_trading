import { useTimeframes } from "@/hooks/useBacktests";
import { cn } from "@/lib/utils";

interface Props {
  value: string;
  onChange: (token: string) => void;
  /** Restrict to these canonical tokens (e.g. a strategy's supported set). */
  allowed?: string[];
  className?: string;
}

const FALLBACK = ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"];

export function TimeframeSelect({ value, onChange, allowed, className }: Props) {
  const { data } = useTimeframes();
  const tokens = (data?.map((t) => t.token) ?? FALLBACK).filter(
    (t) => !allowed || allowed.includes(t),
  );

  return (
    <div className={cn("inline-flex rounded-md border border-line-strong bg-surface p-0.5", className)}>
      {tokens.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onChange(t)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium transition-colors",
            t === value
              ? "bg-emerald-600/20 text-emerald-300"
              : "text-fg-muted hover:text-fg",
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
