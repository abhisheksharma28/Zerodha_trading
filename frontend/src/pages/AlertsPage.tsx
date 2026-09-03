import { useState } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMarkAlertsRead, useScannerAlerts } from "@/hooks/useMarketScanner";
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

function ScannerNotifications() {
  const { data } = useScannerAlerts();
  const mark = useMarkAlertsRead();
  const alerts = data?.alerts ?? [];
  if (alerts.length === 0) {
    return <p className="py-8 text-center text-sm text-fg-faint">No scanner notifications yet.</p>;
  }
  const tone: Record<string, string> = {
    NEW_TRADE: "border-l-accent",
    TARGET: "border-l-pos",
    SL: "border-l-neg",
    NEUTRAL: "border-l-amber-400",
  };
  return (
    <div>
      <div className="flex items-center justify-between px-3 py-2 text-xs text-fg-faint">
        <span>
          Market Scanner · {data?.unread ?? 0} unread. Delivery to push / email is wired later; this is
          the in-app feed.
        </span>
        {(data?.unread ?? 0) > 0 && (
          <button type="button" className="text-accent hover:underline" onClick={() => mark.mutate(undefined)}>
            Mark all read
          </button>
        )}
      </div>
      <ul className="divide-y divide-line/60">
        {alerts.map((a) => (
          <li
            key={a.id}
            className={cn(
              "border-l-2 px-3 py-2 text-sm",
              tone[a.kind] ?? "border-l-line",
              a.read ? "opacity-60" : "",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-fg">{a.title}</span>
              <span className="shrink-0 text-[11px] text-fg-faint">
                {a.created_at ? new Date(a.created_at).toLocaleString("en-IN") : ""}
              </span>
            </div>
            <p className="text-xs text-fg-muted">{a.body}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function AlertsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Alerts");

  const cols: Column<Alert>[] = [
    {
      key: "name",
      header: "Name",
      cell: (a) => <span className="font-medium text-fg">{a.name}</span>,
      sortValue: (a) => a.name,
    },
    {
      key: "cond",
      header: "Condition",
      cell: (a) => <span className="text-fg-muted">{a.condition}</span>,
      sortValue: (a) => a.condition,
    },
    { key: "inst", header: "Instrument", cell: (a) => a.instrument, sortValue: (a) => a.instrument },
    {
      key: "status",
      header: "Status",
      cell: (a) => (
        <Badge variant={a.status === "Active" ? "success" : "warning"}>{a.status}</Badge>
      ),
      sortValue: (a) => a.status,
    },
    {
      key: "last",
      header: "Last triggered",
      align: "right",
      cell: (a) => a.lastTriggered,
      sortValue: (a) => a.lastTriggered,
    },
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
          <DataTable
            columns={cols}
            rows={SAMPLE}
            rowKey={(a) => a.name}
            searchable
            searchPlaceholder="Filter alerts…"
          />
        ) : (
          <ScannerNotifications />
        )}
      </SectionCard>
    </div>
  );
}
