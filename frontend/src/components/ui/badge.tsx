import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-neutral-700 bg-neutral-800 text-neutral-200",
        success: "border-emerald-500/50 bg-emerald-500/10 text-emerald-400",
        warning: "border-amber-500/50 bg-amber-500/10 text-amber-400",
        destructive: "border-red-500/50 bg-red-500/10 text-red-400",
        info: "border-sky-500/50 bg-sky-500/10 text-sky-400",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
