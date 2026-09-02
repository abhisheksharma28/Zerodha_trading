import { useEffect, useRef, useState, type ReactNode } from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

/** Small circled "i" that opens a click-toggled popover (title= tooltips are
 *  unreliable on touch and get clipped). */
export function InfoButton({
  children,
  className,
  align = "right",
  label = "More info",
}: {
  children: ReactNode;
  className?: string;
  align?: "left" | "right";
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div ref={ref} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-4 w-4 items-center justify-center rounded-full text-fg-faint transition-colors hover:text-fg",
          open && "text-accent",
        )}
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div
          className={cn(
            "absolute top-full z-50 mt-1.5 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line-strong bg-surface p-3 text-xs leading-relaxed text-fg-muted shadow-xl",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
