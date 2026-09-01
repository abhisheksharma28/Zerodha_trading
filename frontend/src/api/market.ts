import { apiClient } from "@/api/client";
import type { MarketOverview } from "@/types/api";

export const marketApi = {
  overview: (universe = "nifty50") =>
    apiClient
      .get<MarketOverview>("/market/overview", { params: { universe } })
      .then((r) => r.data),
};
