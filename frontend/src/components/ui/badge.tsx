import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-line-strong bg-elevated text-fg",
        success: "border-pos/50 bg-pos/10 text-pos",
        warning: "border-amber-500/50 bg-amber-500/10 text-amber-400",
        destructive: "border-red-500/50 bg-red-500/10 text-neg",
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
