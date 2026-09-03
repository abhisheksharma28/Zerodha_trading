import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Sparkline } from "@/components/Sparkline";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  delta,
  deltaTone,
  icon: Icon,
  spark,
  valueClassName,
}: {
  label: string;
  value: string | number;
  delta?: string;
  deltaTone?: "pos" | "neg" | "muted";
  icon?: LucideIcon;
  spark?: number[];
  valueClassName?: string;
}) {
  const tone =
    deltaTone === "pos"
      ? "text-pos"
      : deltaTone === "neg"
        ? "text-neg"
        : "text-fg-muted";
  return (
    <Card className="hover-lift hover:border-line-strong">
      <CardContent className="flex items-start justify-between gap-3 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-fg-faint">
            {Icon && <Icon className="h-3.5 w-3.5" />}
            <span className="truncate">{label}</span>
          </div>
          <p className={cn("font-display mt-1.5 text-2xl font-semibold tabular-nums", valueClassName)}>
            {value}
          </p>
          {delta && <p className={cn("mt-0.5 text-xs font-medium tabular-nums", tone)}>{delta}</p>}
        </div>
        {spark && spark.length > 1 && (
          <div className="h-10 w-20 shrink-0">
            <Sparkline data={spark} tone={deltaTone === "neg" ? "neg" : "accent"} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
