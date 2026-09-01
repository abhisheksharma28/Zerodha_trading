import { useState } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Alert {
  name: string;
  condition: string;
  instrument: string;
  status: "Active" | "Paused";
  lastTriggered: string;
}

const SAMPLE: Alert[] = [
  { name: "NIFTY above 25000", condition: "Price > 25000", instrument: "NIFTY 50", status: "Active", lastTriggered: "—" },
  { name: "BankNifty breakout", condition: "Price > 51500", instrument: "BANKNIFTY", status: "Active", lastTriggered: "—" },
  { name: "RSI overbought", condition: "RSI(14) > 70", instrument: "RELIANCE", status: "Paused", lastTriggered: "—" },
  { name: "Daily loss limit", condition: "P&L < -2%", instrument: "Portfolio", status: "Active", lastTriggered: "—" },
];

const TABS = ["Alerts", "Notifications"] as const;

export default function AlertsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Alerts");

  const cols: Column<Alert>[] = [
    { key: "name", header: "Name", cell: (a) => <span className="font-medium text-fg">{a.name}</span> },
    { key: "cond", header: "Condition", cell: (a) => <span className="text-fg-muted">{a.condition}</span> },
    { key: "inst", header: "Instrument", cell: (a) => a.instrument },
    {
      key: "status",
      header: "Status",
      cell: (a) => (
        <Badge variant={a.status === "Active" ? "success" : "warning"}>{a.status}</Badge>
      ),
    },
    { key: "last", header: "Last triggered", align: "right", cell: (a) => a.lastTriggered },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Alerts & Notifications"
        subtitle="Price, indicator and risk alerts across your instruments and portfolio."
        actions={<Button size="sm">New Alert</Button>}
      />

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-300">
        Alert delivery (price/indicator evaluation and notifications) is wired in the live-data
        phase. The rows below are a sample layout.
      </div>

      <SectionCard title={tab} bodyClassName="p-0">
        <div className="flex gap-1 border-b border-line px-3 pt-3">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "rounded-t-md px-3 py-1.5 text-xs font-medium",
                t === tab ? "bg-elevated text-fg" : "text-fg-muted hover:text-fg",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "Alerts" ? (
          <DataTable columns={cols} rows={SAMPLE} rowKey={(a) => a.name} />
        ) : (
          <p className="py-8 text-center text-sm text-fg-faint">No notifications yet.</p>
        )}
      </SectionCard>
    </div>
  );
}
