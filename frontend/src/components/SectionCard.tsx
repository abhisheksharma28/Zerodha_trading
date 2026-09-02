import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Titled panel with the numbered / accent-labelled header treatment used
 *  across the platform (see the AlgoEdge layout). */
export function SectionCard({
  title,
  index,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title: ReactNode;
  index?: number;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2">
          {index != null && (
            <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold text-accent">
              {index}
            </span>
          )}
          <h2 className="text-sm font-semibold text-fg">{title}</h2>
        </div>
        {actions}
      </div>
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </Card>
  );
}
