import { lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";

// Route components are code-split: the initial load ships only the shell +
// the first route's chunk instead of every page's JS (recharts /
// lightweight-charts included). Each page is a default export.
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const StrategiesPage = lazy(() => import("@/pages/StrategiesPage"));
const StrategyDetailPage = lazy(() => import("@/pages/StrategyDetailPage"));
const StrategyLibraryPage = lazy(() => import("@/pages/StrategyLibraryPage"));
const StrategyTemplateDetailPage = lazy(() => import("@/pages/StrategyTemplateDetailPage"));
const LeaderboardPage = lazy(() => import("@/pages/LeaderboardPage"));
const ArbitrageLibraryPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbitrageLibraryPage })));
const ArbScannerPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbScannerPage })));
const ArbPairDiscoveryPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbPairDiscoveryPage })));
const ArbBacktestPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbBacktestPage })));
const ArbPaperPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbPaperPage })));
const ArbLiveMonitorPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbLiveMonitorPage })));
const ArbPortfolioPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbPortfolioPage })));
const ArbAnalyticsPage = lazy(() => import("@/pages/ArbitrageLabPages").then((m) => ({ default: m.ArbAnalyticsPage })));
const OptionsHniPage = lazy(() => import("@/pages/OptionsHniPage"));
const BacktestsPage = lazy(() => import("@/pages/BacktestsPage"));
const BacktestDetailPage = lazy(() => import("@/pages/BacktestDetailPage"));
const DeploymentsPage = lazy(() => import("@/pages/DeploymentsPage"));
const DeploymentDetailPage = lazy(() => import("@/pages/DeploymentDetailPage"));
const MonitoringPage = lazy(() => import("@/pages/MonitoringPage"));
const TradeLogsPage = lazy(() => import("@/pages/TradeLogsPage"));
const AuditLogsPage = lazy(() => import("@/pages/AuditLogsPage"));
const BrokerPage = lazy(() => import("@/pages/BrokerPage"));
const MarketScannerPage = lazy(() => import("@/pages/MarketScannerPage"));
const StockDetailPage = lazy(() => import("@/pages/StockDetailPage"));
const OptionChainPage = lazy(() => import("@/pages/OptionChainPage"));
const OptionStrategyPage = lazy(() => import("@/pages/OptionStrategyPage"));
const ChartingPage = lazy(() => import("@/pages/ChartingPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const AlertsPage = lazy(() => import("@/pages/AlertsPage"));
const ReportsPage = lazy(() => import("@/pages/ReportsPage"));
const PositionsPage = lazy(() => import("@/pages/PositionsPage"));
const OrdersPage = lazy(() => import("@/pages/OrdersPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<MarketScannerPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="strategy-library" element={<StrategyLibraryPage />} />
        <Route path="strategy-library/:slug" element={<StrategyTemplateDetailPage />} />
        <Route path="leaderboard" element={<LeaderboardPage />} />
        <Route path="arbitrage" element={<ArbitrageLibraryPage />} />
        <Route path="arbitrage/scanner" element={<ArbScannerPage />} />
        <Route path="arbitrage/pair-discovery" element={<ArbPairDiscoveryPage />} />
        <Route path="arbitrage/backtest" element={<ArbBacktestPage />} />
        <Route path="arbitrage/paper" element={<ArbPaperPage />} />
        <Route path="arbitrage/live" element={<ArbLiveMonitorPage />} />
        <Route path="arbitrage/portfolio" element={<ArbPortfolioPage />} />
        <Route path="arbitrage/analytics" element={<ArbAnalyticsPage />} />
        <Route path="options-hni" element={<OptionsHniPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="backtests/:backtestId" element={<BacktestDetailPage />} />
        <Route path="deployments" element={<DeploymentsPage />} />
        <Route path="deployments/:deploymentId" element={<DeploymentDetailPage />} />
        <Route path="monitoring" element={<MonitoringPage />} />
        <Route path="market-scanner" element={<MarketScannerPage />} />
        <Route path="stocks/:exchange/:symbol" element={<StockDetailPage />} />
        <Route path="option-chain" element={<OptionChainPage />} />
        <Route path="option-strategy" element={<OptionStrategyPage />} />
        <Route path="charting" element={<ChartingPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="trade-logs" element={<TradeLogsPage />} />
        <Route path="audit-logs" element={<AuditLogsPage />} />
        <Route path="broker" element={<BrokerPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
