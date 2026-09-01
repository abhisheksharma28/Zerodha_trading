import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { useBrokerStatus } from "@/hooks/useBroker";

export default function PositionsPage() {
  const { data: broker } = useBrokerStatus();

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Positions"
        subtitle="Live net positions from your connected Zerodha account."
      />
      <SectionCard title="Open Positions">
        {broker?.connected ? (
          <p className="py-8 text-center text-sm text-fg-faint">
            No open positions. Live position streaming is delivered in the market-data phase; this
            view will never show placeholder holdings as real.
          </p>
        ) : (
          <div className="py-8 text-center">
            <p className="text-sm text-fg-muted">Broker not connected.</p>
            <Link
              to="/broker"
              className="mt-2 inline-block rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:bg-accent-strong"
            >
              Connect Zerodha
            </Link>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
