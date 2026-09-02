import { useQuery } from "@tanstack/react-query";

import { orderflowApi } from "@/api/orderflow";

interface WindowOpts {
  timeframe?: string;
  days?: number;
  from?: string;
  to?: string;
}

export function useOrderFlowCapabilities() {
  return useQuery({
    queryKey: ["orderflow", "capabilities"],
    queryFn: () => orderflowApi.capabilities("all"),
    staleTime: 60 * 60_000,
  });
}

export function useVolumeProfile(
  symbol: string | undefined,
  opts: WindowOpts & { valueArea?: number; binMultiple?: number; enabled?: boolean } = {},
) {
  const { enabled = true, ...o } = opts;
  return useQuery({
    queryKey: ["orderflow", "volume-profile", symbol, o.timeframe, o.days, o.from, o.to, o.valueArea, o.binMultiple],
    queryFn: () => orderflowApi.volumeProfile(symbol!, o),
    enabled: !!symbol && enabled,
    staleTime: 30_000,
  });
}

export function useAnchoredVwap(
  symbol: string | undefined,
  opts: WindowOpts & { anchor?: string; enabled?: boolean } = {},
) {
  const { enabled = true, ...o } = opts;
  return useQuery({
    queryKey: ["orderflow", "vwap", symbol, o.timeframe, o.days, o.from, o.to, o.anchor],
    queryFn: () => orderflowApi.vwap(symbol!, o),
    enabled: !!symbol && enabled,
    staleTime: 30_000,
  });
}

export function useEstimatedDelta(
  symbol: string | undefined,
  opts: { limit?: number; enabled?: boolean; refetchMs?: number } = {},
) {
  const { enabled = true, limit = 240, refetchMs = 5_000 } = opts;
  return useQuery({
    queryKey: ["orderflow", "estimated-delta", symbol, limit],
    queryFn: () => orderflowApi.estimatedDelta(symbol!, limit),
    enabled: !!symbol && enabled,
    refetchInterval: refetchMs,
    refetchIntervalInBackground: false,
    staleTime: refetchMs,
  });
}
