import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { instrumentsApi } from "@/api/instruments";

/** Debounce any fast-changing value (e.g. a search box). */
export function useDebouncedValue<T>(value: T, delayMs = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

export function useInstrumentSearch(
  query: string,
  opts: { exchange?: string; instrument_type?: string; limit?: number } = {},
) {
  const q = useDebouncedValue(query.trim(), 200);
  return useQuery({
    queryKey: ["instruments", "search", q, opts],
    queryFn: () => instrumentsApi.search({ q, ...opts }),
    enabled: q.length >= 1,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useUnderlyings(exchange = "NFO") {
  return useQuery({
    queryKey: ["instruments", "underlyings", exchange],
    queryFn: () => instrumentsApi.underlyings(exchange),
    staleTime: 5 * 60_000,
  });
}

export function useExpiries(underlying: string | undefined, exchange = "NFO") {
  return useQuery({
    queryKey: ["instruments", "expiries", underlying, exchange],
    queryFn: () => instrumentsApi.expiries(underlying as string, exchange),
    enabled: !!underlying,
    staleTime: 5 * 60_000,
  });
}
