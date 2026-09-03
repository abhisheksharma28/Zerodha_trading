import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { leaderboardApi } from "@/api/leaderboard";

const KEY = ["leaderboard"] as const;

export function useLeaderboard() {
  return useQuery({
    queryKey: KEY,
    queryFn: leaderboardApi.get,
    staleTime: 60_000,
  });
}

export function useBacktestCatalog() {
  return useQuery({
    queryKey: [...KEY, "catalog"],
    queryFn: leaderboardApi.catalog,
    staleTime: 60_000,
  });
}

export function useSectorSeasonality(years = 10) {
  return useQuery({
    queryKey: [...KEY, "seasonality", years],
    queryFn: () => leaderboardApi.seasonality(years),
    staleTime: 5 * 60_000,
  });
}

export function useLeaderboardDetail(slug: string | undefined) {
  return useQuery({
    queryKey: [...KEY, slug],
    queryFn: () => leaderboardApi.detail(slug as string),
    enabled: !!slug,
  });
}

const REFRESH_STATUS_KEY = [...KEY, "refresh-status"] as const;

export function useRefreshStatus() {
  return useQuery({
    queryKey: REFRESH_STATUS_KEY,
    queryFn: leaderboardApi.refreshStatus,
    staleTime: 0,
    refetchInterval: (q) => (q.state.data?.state === "running" ? 2500 : false),
    refetchOnWindowFocus: true,
  });
}

export function useRefreshLeaderboard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slugs?: string[]) => leaderboardApi.refresh(slugs),
    onSuccess: () => qc.invalidateQueries({ queryKey: REFRESH_STATUS_KEY }),
  });
}

export function useRefreshOne() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => leaderboardApi.refreshOne(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: REFRESH_STATUS_KEY }),
  });
}

export function useCreatePaperDeployments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: leaderboardApi.createPaperDeployments,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRunRobustness() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => leaderboardApi.runRobustness(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRunTuning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => leaderboardApi.runTuning(slug),
    onSuccess: (_d, slug) => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: [...KEY, slug] });
    },
  });
}

export function useRunParamSim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => leaderboardApi.runParamSim(slug),
    onSuccess: (_d, slug) => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: [...KEY, slug] });
    },
  });
}

export function useAdoptTuned() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, overrides }: { slug: string; overrides: Record<string, unknown> | null }) =>
      leaderboardApi.adoptTuned(slug, overrides),
    onSuccess: (_d, { slug }) => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: [...KEY, slug] });
    },
  });
}
