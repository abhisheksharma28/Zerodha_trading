import { useState } from "react";
import { Star } from "lucide-react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface Scanner {
  name: string;
  matches: number;
  favorite: boolean;
}

// Placeholder catalogue — live scanning is wired in the market-data phase.
const SCANNERS: Scanner[] = [
  { name: "High Volume Breakout", matches: 156, favorite: true },
  { name: "Price Above EMA 200", matches: 243, favorite: true },
  { name: "RSI Oversold (< 30)", matches: 89, favorite: false },
  { name: "Bullish Engulfing", matches: 67, favorite: false },
  { name: "Gap Up > 2%", matches: 34, favorite: false },
  { name: "52-Week High", matches: 21, favorite: false },
  { name: "Opening Range Breakout", matches: 48, favorite: true },
];

const TABS = ["All Scanners", "My Scanners", "Favorites"] as const;

export default function MarketScannerPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("All Scanners");
  const [q, setQ] = useState("");

  const rows = SCANNERS.filter((s) => {
    if (tab === "Favorites" && !s.favorite) return false;
    return s.name.toLowerCase().includes(q.toLowerCase());
  });

  const cols: Column<Scanner>[] = [
    {
      key: "name",
      header: "Scanner",
      cell: (s) => <span className="font-medium text-fg">{s.name}</span>,
    },
    { key: "matches", header: "Matches", align: "right", cell: (s) => s.matches },
    {
      key: "fav",
      header: "",
      align: "right",
      cell: (s) => (
        <Star
          className={cn(
            "ml-auto h-4 w-4",
            s.favorite ? "fill-accent text-accent" : "text-fg-faint",
          )}
        />
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Market Scanner"
        subtitle="Screen the NSE universe against technical and volume filters."
        actions={<Button size="sm">New Scanner</Button>}
      />

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-300">
        Scanner results below are a sample catalogue. Live screening against the instrument master
        is delivered in the market-data phase — no fabricated match data is shown as real.
      </div>

      <SectionCard
        title="Scanners"
        actions={
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search scanners…"
            className="h-8 w-48"
          />
        }
        bodyClassName="p-0"
      >
        <div className="flex gap-1 border-b border-line px-3 pt-3">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "rounded-t-md px-3 py-1.5 text-xs font-medium",
                t === tab
                  ? "bg-elevated text-fg"
                  : "text-fg-muted hover:text-fg",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <DataTable columns={cols} rows={rows} rowKey={(s) => s.name} empty="No scanners match." />
      </SectionCard>
    </div>
  );
}
