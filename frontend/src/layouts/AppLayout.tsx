import { Suspense, useCallback, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  CandlestickChart,
  ChevronDown,
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
  Scale,
  Trophy,
  Wallet,
} from "lucide-react";

import { IndexStrip } from "@/components/IndexStrip";
import { LatencyPill } from "@/components/LatencyPill";
import { NavInstrumentSearch } from "@/components/NavInstrumentSearch";
import { StockDrawer } from "@/components/StockDrawer";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";
import { useBrokerStatus } from "@/hooks/useBroker";

type Item = { to: string; label: string; icon: typeof Gauge; desc?: string };

const PRIMARY: Item[] = [
  { to: "/", label: "Scanner", icon: Radar },
  { to: "/dashboard", label: "Dashboard", icon: Gauge },
  { to: "/charting", label: "Charting", icon: CandlestickChart },
];

const MENUS: { label: string; items: Item[] }[] = [
  {
    label: "Research",
    items: [
      { to: "/backtests", label: "Backtest", icon: FlaskConical, desc: "Run & analyse strategies" },
      { to: "/strategy-library", label: "Strategy Library", icon: LibraryBig, desc: "Research-backed templates" },
      { to: "/leaderboard", label: "Leaderboard", icon: Trophy, desc: "Strategy ranking — backtest & paper" },
      { to: "/strategies", label: "My Strategies", icon: ListChecks, desc: "Your saved strategies" },
      { to: "/options-hni", label: "NIFTY Monthly HNI", icon: Layers, desc: "1:3:2 CALL ratio spread" },
      { to: "/analytics", label: "Analytics", icon: BarChart3, desc: "Aggregate performance" },
    ],
  },
  {
    label: "Arbitrage Lab",
    items: [
      { to: "/arbitrage", label: "Strategy Library", icon: Scale, desc: "Honesty-classified arb strategies" },
      { to: "/arbitrage/pair-discovery", label: "Pair Discovery", icon: Radar, desc: "Cointegrated tradeable pairs" },
      { to: "/arbitrage/backtest", label: "Backtesting", icon: FlaskConical, desc: "Dedicated multi-leg engine" },
      { to: "/arbitrage/scanner", label: "Opportunity Scanner", icon: Activity, desc: "Live net-edge screening" },
      { to: "/arbitrage/paper", label: "Paper Trading", icon: Rocket, desc: "Multi-leg paper execution" },
      { to: "/arbitrage/live", label: "Live Monitor", icon: Activity, desc: "Open structures & hedge state" },
      { to: "/arbitrage/portfolio", label: "Portfolio", icon: Wallet, desc: "Arb runs — separate from leaderboard" },
      { to: "/arbitrage/analytics", label: "Analytics", icon: BarChart3, desc: "Backtest vs paper, edge capture" },
    ],
  },
  {
    label: "Adaptive Options",
    items: [
      { to: "/adaptive-options", label: "Dashboard", icon: Gauge, desc: "Market + positioning at a glance" },
      { to: "/adaptive-options/intelligence", label: "Market Intelligence", icon: Activity, desc: "Regime · PCR · OI · IV · expected move" },
      { to: "/adaptive-options/risk-greeks", label: "Risk & Greeks", icon: Scale, desc: "Per-strike & ATM greeks + warnings" },
      { to: "/adaptive-options/strategy-engine", label: "Strategy Engine", icon: ListChecks, desc: "Adaptive selection" },
      { to: "/adaptive-options/strategy-builder", label: "Strategy Builder", icon: Layers, desc: "Strike selection" },
      { to: "/adaptive-options/backtesting", label: "Backtesting", icon: FlaskConical, desc: "Bhavcopy + synthetic" },
      { to: "/adaptive-options/validation", label: "Validation", icon: Radar, desc: "Walk-forward / MC" },
      { to: "/adaptive-options/paper-trading", label: "Paper Trading", icon: Rocket, desc: "Live decision engine" },
      { to: "/adaptive-options/comparison", label: "Strategy Comparison", icon: BarChart3, desc: "Why one over another" },
      { to: "/adaptive-options/decision-log", label: "Decision Log", icon: FileClock, desc: "Every decision, replayable" },
      { to: "/adaptive-options/settings", label: "Settings", icon: SettingsIcon, desc: "Presets & overridable parameters" },
    ],
  },
  {
    label: "Trading",
    items: [
      { to: "/option-chain", label: "Option Chain", icon: Layers, desc: "OI, IV, PCR, max pain" },
      { to: "/option-strategy", label: "Strategy Builder", icon: FlaskConical, desc: "Multi-leg payoff — bull/bear/neutral" },
      { to: "/deployments", label: "Live Trading", icon: Rocket, desc: "Deploy paper / live" },
      { to: "/monitoring", label: "Monitoring", icon: Activity, desc: "Running deployments" },
      { to: "/positions", label: "Positions", icon: Wallet },
      { to: "/orders", label: "Orders", icon: CandlestickChart },
      { to: "/alerts", label: "Alerts", icon: Bell },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/logbook", label: "Scanner Log Book", icon: BookOpen, desc: "Recommendation outcomes & hit-rate" },
      { to: "/reports", label: "Reports", icon: FileText },
      { to: "/audit-logs", label: "Audit Logs", icon: FileClock },
      { to: "/broker", label: "Broker", icon: Plug },
      { to: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

const linkCls = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
    isActive ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-elevated hover:text-fg",
  );

export function AppLayout() {
  const { data: broker } = useBrokerStatus();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const navigate = useNavigate();
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openNow = useCallback((label: string) => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpenMenu(label);
  }, []);
  const closeSoon = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpenMenu(null), 320);
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-bg text-fg">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-2 px-4">
          <button
            type="button"
            onClick={() => navigate("/")}
            className="mr-2 flex items-center gap-2"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-fg">
              <CandlestickChart className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold tracking-tight">AlgoEdge</span>
          </button>

          <nav className="flex items-center gap-0.5" onMouseLeave={closeSoon}>
            {PRIMARY.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === "/"} className={linkCls}>
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
            {MENUS.map((menu) => (
              <div
                key={menu.label}
                className="relative"
                onMouseEnter={() => openNow(menu.label)}
                onMouseLeave={closeSoon}
              >
                <button
                  type="button"
                  onClick={() => setOpenMenu((m) => (m === menu.label ? null : menu.label))}
                  className={cn(
                    "flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                    openMenu === menu.label
                      ? "bg-elevated text-fg"
                      : "text-fg-muted hover:bg-elevated hover:text-fg",
                  )}
                >
                  {menu.label}
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {openMenu === menu.label && (
                  <div
                    className="animate-menu absolute left-0 top-full z-50 w-64 rounded-lg border border-line-strong bg-surface p-1.5 pt-2 shadow-xl"
                    onMouseEnter={() => openNow(menu.label)}
                  >
                    {menu.items.map(({ to, label, icon: Icon, desc }) => (
                      <NavLink
                        key={to}
                        to={to}
                        onClick={() => setOpenMenu(null)}
                        className={({ isActive }) =>
                          cn(
                            "flex items-start gap-2.5 rounded-md px-2.5 py-2 transition-colors",
                            isActive ? "bg-accent-soft" : "hover:bg-elevated",
                          )
                        }
                      >
                        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                        <span>
                          <span className="block text-sm font-medium text-fg">{label}</span>
                          {desc && <span className="block text-xs text-fg-faint">{desc}</span>}
                        </span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </nav>

          <NavInstrumentSearch />

          <div className="ml-auto flex items-center gap-3 sm:ml-3">
            <span className="hidden items-center gap-1.5 text-xs md:flex">
              <span className={cn("h-2 w-2 rounded-full", broker?.connected ? "bg-pos" : "bg-line-strong")} />
              <span className="text-fg-muted">
                {broker?.connected ? broker.kite_user_id ?? "Connected" : "Broker offline"}
              </span>
            </span>
            <span className="h-4 w-px bg-line-strong" />
            <LatencyPill />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <IndexStrip />

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
        <div className="animate-in">
          <Suspense
            fallback={
              <div className="flex items-center gap-2 py-16 text-sm text-fg-faint">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
                Loading…
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </div>
      </main>

      <StockDrawer />
    </div>
  );
}
