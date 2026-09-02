import { useEffect, useRef, useState } from "react";

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

// Latest tick per symbol for a set of symbols. Incoming ticks are buffered
// and flushed on a short interval so a fast market can't cause a render per
// tick when hundreds of instruments are subscribed.
export function useLiveTicks(symbols: string[], flushMs = 250) {
  const key = [...symbols].sort().join(",");
  const [ticks, setTicks] = useState<Record<string, LiveTick>>({});
  const [status, setStatus] = useState<StreamStatus>(marketStream.getStatus());
  const buf = useRef<Record<string, LiveTick>>({});
  const dirty = useRef(false);

  useEffect(() => marketStream.onStatus(() => setStatus(marketStream.getStatus())), []);

  useEffect(() => {
    if (symbols.length === 0) return;
    const unsubs = symbols.map((sym) =>
      marketStream.subscribe(sym, (t) => {
        buf.current[sym] = t;
        dirty.current = true;
      }),
    );
    const timer = setInterval(() => {
      if (!dirty.current) return;
      dirty.current = false;
      setTicks((prev) => ({ ...prev, ...buf.current }));
    }, flushMs);
    return () => {
      clearInterval(timer);
      for (const u of unsubs) u();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, flushMs]);

  return { ticks, status };
}
