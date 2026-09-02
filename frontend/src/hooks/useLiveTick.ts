import { useEffect, useState } from "react";

import { marketStream, type LiveTick, type StreamStatus } from "@/lib/marketStream";

// Latest live tick for one exchange-qualified symbol (e.g. "NSE:RELIANCE"),
// plus the shared stream connection status.
export function useLiveTick(symbol: string | undefined) {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [status, setStatus] = useState<StreamStatus>(marketStream.getStatus());

  useEffect(() => marketStream.onStatus(() => setStatus(marketStream.getStatus())), []);

  useEffect(() => {
    if (!symbol) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset stale tick when the symbol changes
    setTick(null);
    return marketStream.subscribe(symbol, setTick);
  }, [symbol]);

  return { tick, status };
}
