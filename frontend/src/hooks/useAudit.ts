import { useQuery } from "@tanstack/react-query";

import { auditApi } from "@/api/audit";

export function useAuditLogs(limit = 100) {
  return useQuery({ queryKey: ["audit-logs", limit], queryFn: () => auditApi.list(limit) });
}

export function useChangeLog(entityType: string, entityId: string | undefined) {
  return useQuery({
    queryKey: ["change-log", entityType, entityId],
    queryFn: () => auditApi.changeLog(entityType, entityId as string),
    enabled: !!entityId,
  });
}
