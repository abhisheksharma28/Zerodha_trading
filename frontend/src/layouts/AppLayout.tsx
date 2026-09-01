import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  FileClock,
  Gauge,
  History,
  Layers,
  Library,
  ListChecks,
  Plug,
  Rocket,
  ScrollText,
} from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";
import { useBrokerStatus } from "@/hooks/useBroker";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/strategy-library", label: "Strategy Library", icon: Library },
  { to: "/options-hni", label: "NIFTY Monthly HNI", icon: Layers },
  { to: "/strategies", label: "My Strategies", icon: ListChecks },
  { to: "/backtests", label: "Backtests", icon: History },
  { to: "/deployments", label: "Deployments", icon: Rocket },
  { to: "/monitoring", label: "Monitoring", icon: Activity },
  { to: "/trade-logs", label: "Trade Logs", icon: ScrollText },
  { to: "/audit-logs", label: "Audit Logs", icon: FileClock },
  { to: "/broker", label: "Broker Connection", icon: Plug },
];

export function AppLayout() {
  const { data: brokerStatus } = useBrokerStatus();

  return (
    <div className="flex min-h-screen bg-bg text-fg">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface/40">
        <div className="flex items-start justify-between border-b border-line px-4 py-4">
          <div>
            <p className="text-sm font-semibold tracking-tight">Trading Strategy Platform</p>
            <p className="text-xs text-fg-faint">Zerodha Kite Connect</p>
          </div>
          <ThemeToggle />
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 p-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-emerald-600/15 text-emerald-400"
                    : "text-fg-muted hover:bg-elevated hover:text-fg",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                brokerStatus?.connected ? "bg-emerald-500" : "bg-elevated",
              )}
            />
            <span className="text-fg-muted">
              {brokerStatus?.connected
                ? `Connected as ${brokerStatus.kite_user_id ?? "Zerodha"}`
                : "Broker not connected"}
            </span>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
