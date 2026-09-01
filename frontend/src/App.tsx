import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";
import DashboardPage from "@/pages/DashboardPage";
import StrategiesPage from "@/pages/StrategiesPage";
import StrategyDetailPage from "@/pages/StrategyDetailPage";
import StrategyLibraryPage from "@/pages/StrategyLibraryPage";
import StrategyTemplateDetailPage from "@/pages/StrategyTemplateDetailPage";
import OptionsHniPage from "@/pages/OptionsHniPage";
import BacktestsPage from "@/pages/BacktestsPage";
import BacktestDetailPage from "@/pages/BacktestDetailPage";
import DeploymentsPage from "@/pages/DeploymentsPage";
import DeploymentDetailPage from "@/pages/DeploymentDetailPage";
import MonitoringPage from "@/pages/MonitoringPage";
import TradeLogsPage from "@/pages/TradeLogsPage";
import AuditLogsPage from "@/pages/AuditLogsPage";
import BrokerPage from "@/pages/BrokerPage";
import MarketScannerPage from "@/pages/MarketScannerPage";
import OptionChainPage from "@/pages/OptionChainPage";
import ChartingPage from "@/pages/ChartingPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import AlertsPage from "@/pages/AlertsPage";
import ReportsPage from "@/pages/ReportsPage";
import PositionsPage from "@/pages/PositionsPage";
import OrdersPage from "@/pages/OrdersPage";
import SettingsPage from "@/pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<MarketScannerPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="strategy-library" element={<StrategyLibraryPage />} />
        <Route path="strategy-library/:slug" element={<StrategyTemplateDetailPage />} />
        <Route path="options-hni" element={<OptionsHniPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="backtests/:backtestId" element={<BacktestDetailPage />} />
        <Route path="deployments" element={<DeploymentsPage />} />
        <Route path="deployments/:deploymentId" element={<DeploymentDetailPage />} />
        <Route path="monitoring" element={<MonitoringPage />} />
        <Route path="market-scanner" element={<MarketScannerPage />} />
        <Route path="option-chain" element={<OptionChainPage />} />
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
