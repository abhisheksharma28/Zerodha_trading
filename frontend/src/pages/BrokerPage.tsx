import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useExchangeBrokerSession, useBrokerStatus } from "@/hooks/useBroker";
import { brokerApi } from "@/api/broker";

export default function BrokerPage() {
  const { data: status } = useBrokerStatus();
  const [requestToken, setRequestToken] = useState("");
  const exchange = useExchangeBrokerSession();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Broker Connection</h1>
        <p className="text-sm text-neutral-400">
          Zerodha access tokens expire at ~6 AM IST every day (a regulatory requirement, not a bug)
          — reconnecting here each trading morning is expected. See docs/ZERODHA_API_NOTES.md.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Status</CardTitle>
        </CardHeader>
        <CardContent>
          {status?.connected ? (
            <div className="flex flex-col gap-1 text-sm">
              <p className="text-emerald-400">Connected as {status.kite_user_id}</p>
              <p className="text-xs text-neutral-500">
                Session expires {status.expires_at ? new Date(status.expires_at).toLocaleString() : "—"}
              </p>
            </div>
          ) : (
            <p className="text-sm text-neutral-400">Not connected.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Connect / reconnect</CardTitle>
          <CardDescription>
            Kite Connect requires a human login in the browser — there is no password grant. Click
            through to log in, then paste the <code>request_token</code> from the redirect URL back
            here.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Button
            variant="outline"
            onClick={async () => {
              const { login_url } = await brokerApi.loginUrl();
              window.open(login_url, "_blank", "noopener,noreferrer");
            }}
          >
            Open Zerodha login <ExternalLink className="h-4 w-4" />
          </Button>

          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              exchange.mutate(requestToken);
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="request-token">request_token</Label>
              <Input
                id="request-token"
                value={requestToken}
                onChange={(e) => setRequestToken(e.target.value)}
                placeholder="Paste the request_token query param here"
              />
            </div>
            {exchange.isError && (
              <p className="text-xs text-red-400">{(exchange.error as Error).message}</p>
            )}
            <div>
              <Button type="submit" disabled={exchange.isPending || !requestToken}>
                {exchange.isPending ? "Connecting…" : "Complete connection"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
