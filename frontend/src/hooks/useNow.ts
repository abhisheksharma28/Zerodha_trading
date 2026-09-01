import { useEffect, useState } from "react";

/** A clock that re-renders on a fixed interval (default 1s). Use for
 *  "updated Ns ago" style displays without coupling to a data refetch. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
