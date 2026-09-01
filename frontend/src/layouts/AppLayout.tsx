import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Bell,
  CandlestickChart,
  ChevronLeft,
  FileClock,
  FileText,
  FlaskConical,
  Gauge,
  Layers,
  LibraryBig,
  ListChecks,
  Plug,
  Radar,
  Rocket,
  Settings as SettingsIcon,
  Wallet,
} from "lucide-react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";
import { useBrokerStatus } from "@/hooks/useBroker";

type NavItem = { to: string; label: string; icon: typeof Gauge; end?: boolean };
type NavGroup = { heading: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    heading: "Overview",
    items: [{ to: "/", label: "Dashboard", icon: Gauge, end: true }],
  },
  {
    heading: "Research",
    items: [
      { to: "/backtests", label: "Backtest", icon: FlaskConical },
      { to: "/strategy-library", label: "Strategy Library", icon: LibraryBig },
      { to: "/strategies", label: "My Strategies", icon: ListChecks },
      { to: "/options-hni", label: "NIFTY Monthly HNI", icon: Layers },
      { to: "/market-scanner", label: "Market Scanner", icon: Radar },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    heading: "Trading",
    items: [
      { to: "/deployments", label: "Live Trading", icon: Rocket },
      { to: "/monitoring", label: "Monitoring", icon: Activity },
      { to: "/positions", label: "Positions", icon: Wallet },
      { to: "/orders", label: "Orders", icon: CandlestickChart },
      { to: "/alerts", label: "Alerts", icon: Bell },
    ],
  },
  {
    heading: "System",
    items: [
      { to: "/reports", label: "Reports", icon: FileText },
      { to: "/audit-logs", label: "Audit Logs", icon: FileClock },
      { to: "/broker", label: "Broker", icon: Plug },
      { to: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

const COLLAPSE_KEY = "ui-sidebar-collapsed";

export function AppLayout() {
  const { data: brokerStatus } = useBrokerStatus();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  return (
    <div className="flex min-h-screen bg-bg text-fg">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-line bg-surface/50 transition-[width] duration-200",
          collapsed ? "w-14" : "w-60",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-3.5">
          {!collapsed && (
            <div className="flex items-center gap-2 overflow-hidden">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent text-accent-fg">
                <CandlestickChart className="h-3.5 w-3.5" />
              </span>
              <div className="leading-tight">
                <p className="text-sm font-semibold tracking-tight">AlgoEdge</p>
                <p className="text-[10px] text-fg-faint">Zerodha Kite</p>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-elevated hover:text-fg"
          >
            <ChevronLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-4 overflow-y-auto p-2">
          {NAV.map((group) => (
            <div key={group.heading} className="flex flex-col gap-0.5">
              {!collapsed && (
                <p className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-fg-faint">
                  {group.heading}
                </p>
              )}
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  title={collapsed ? label : undefined}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      collapsed && "justify-center px-0",
                      isActive
                        ? "bg-accent-soft text-accent"
                        : "text-fg-muted hover:bg-elevated hover:text-fg",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && <span className="truncate">{label}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="flex items-center justify-between gap-2 border-t border-line p-3">
          <div className="flex items-center gap-2 overflow-hidden text-xs">
            <span
              className={cn(
                "h-2 w-2 shrink-0 rounded-full",
                brokerStatus?.connected ? "bg-pos" : "bg-line-strong",
              )}
            />
            {!collapsed && (
              <span className="truncate text-fg-muted">
                {brokerStatus?.connected
                  ? `Connected · ${brokerStatus.kite_user_id ?? "Zerodha"}`
                  : "Broker not connected"}
              </span>
            )}
          </div>
          {!collapsed && <ThemeToggle />}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-6 py-6">
          <div className="animate-in">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
}
