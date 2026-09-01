import { apiClient } from "@/api/client";
import type { AuditLogRow, ChangeLogEntryRow } from "@/types/api";

export const auditApi = {
  list: (limit = 100) =>
    apiClient.get<AuditLogRow[]>("/audit-logs", { params: { limit } }).then((r) => r.data),
  changeLog: (entityType: string, entityId: string) =>
    apiClient
      .get<ChangeLogEntryRow[]>("/change-log", { params: { entity_type: entityType, entity_id: entityId } })
      .then((r) => r.data),
};
