import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/layouts/AppLayout";
import DashboardPage from "@/pages/DashboardPage";
import StrategiesPage from "@/pages/StrategiesPage";
import StrategyDetailPage from "@/pages/StrategyDetailPage";
import BacktestsPage from "@/pages/BacktestsPage";
import BacktestDetailPage from "@/pages/BacktestDetailPage";
import DeploymentsPage from "@/pages/DeploymentsPage";
import DeploymentDetailPage from "@/pages/DeploymentDetailPage";
import MonitoringPage from "@/pages/MonitoringPage";
import TradeLogsPage from "@/pages/TradeLogsPage";
import AuditLogsPage from "@/pages/AuditLogsPage";
import BrokerPage from "@/pages/BrokerPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="backtests/:backtestId" element={<BacktestDetailPage />} />
        <Route path="deployments" element={<DeploymentsPage />} />
        <Route path="deployments/:deploymentId" element={<DeploymentDetailPage />} />
        <Route path="monitoring" element={<MonitoringPage />} />
        <Route path="trade-logs" element={<TradeLogsPage />} />
        <Route path="audit-logs" element={<AuditLogsPage />} />
        <Route path="broker" element={<BrokerPage />} />
      </Route>
    </Routes>
  );
}
