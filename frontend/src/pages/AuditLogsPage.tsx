import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuditLogs } from "@/hooks/useAudit";

export default function AuditLogsPage() {
  const { data: logs, isLoading } = useAuditLogs(200);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Audit Logs</h1>
        <p className="text-sm text-neutral-400">
          Append-only record of every state-changing action — creates, mode transitions, order
          placements, risk breaches.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
          <ul className="flex flex-col gap-2">
            {logs?.map((log) => (
              <li key={log.id} className="rounded-md border border-neutral-800 p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge>{log.action}</Badge>
                    <span className="text-xs text-neutral-500">{log.entity_type}</span>
                  </div>
                  <span className="text-xs text-neutral-500">
                    {new Date(log.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-sm">{log.summary}</p>
              </li>
            ))}
          </ul>
          {logs?.length === 0 && !isLoading && (
            <p className="text-sm text-neutral-500">No audit events yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
