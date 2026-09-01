import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  FileClock,
  Gauge,
  History,
  Library,
  ListChecks,
  Plug,
  Rocket,
  ScrollText,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useBrokerStatus } from "@/hooks/useBroker";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/strategy-library", label: "Strategy Library", icon: Library },
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
    <div className="flex min-h-screen bg-neutral-950 text-neutral-100">
      <aside className="flex w-60 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900/40">
        <div className="border-b border-neutral-800 px-4 py-4">
          <p className="text-sm font-semibold tracking-tight">Trading Strategy Platform</p>
          <p className="text-xs text-neutral-500">Zerodha Kite Connect</p>
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
                    : "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-neutral-800 p-3">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                brokerStatus?.connected ? "bg-emerald-500" : "bg-neutral-600",
              )}
            />
            <span className="text-neutral-400">
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
