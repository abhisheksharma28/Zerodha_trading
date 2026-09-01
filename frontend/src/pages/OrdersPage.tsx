import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";

export default function OrdersPage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Orders"
        subtitle="Order history across paper, simulation and live deployments."
      />
      <SectionCard title="Recent Orders">
        <p className="py-8 text-center text-sm text-fg-faint">
          Per-deployment order logs are available under{" "}
          <Link to="/deployments" className="text-accent hover:underline">
            Live Trading
          </Link>
          . A consolidated cross-deployment order feed lands with the live-data phase.
        </p>
      </SectionCard>
    </div>
  );
}
