import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import type { Basket } from "@/api/baskets";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import {
  useBasketStatus,
  useBaskets,
  useDeployBasket,
  useRebalanceBasket,
  useUndeployBasket,
} from "@/hooks/useBaskets";
import { inr, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

export function DeployedBaskets() {
  const nav = useNavigate();
  const { data: baskets = [], isLoading } = useBaskets();
  const deployed = baskets.filter((b) => b.status === "deployed");
  const draft = baskets.filter((b) => b.status === "draft");

  const [picking, setPicking] = useState(false);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const deploy = useDeployBasket(pick);

  const onDeploy = async () => {
    if (!pick) return;
    setErr(null);
    try {
      await deploy.mutateAsync();
      setPicking(false);
      setPick("");
    } catch (e) {
      setErr(
        (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data
          ?.message ??
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Deploy failed.",
      );
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-fg-faint">
          Deploy a basket to forward-test it in this paper account. It holds CNC positions tagged
          to the basket and rebalances on its schedule.
        </p>
        <Button size="sm" onClick={() => setPicking((v) => !v)}>
          {picking ? "Close" : "+ Deploy a basket"}
        </Button>
      </div>

      {picking && (
        <SectionCard title="Deploy a basket">
          <div className="flex flex-col gap-3 p-4">
            {draft.length === 0 ? (
              <p className="text-sm text-fg-muted">
                No draft baskets to deploy.{" "}
                <button className="text-accent hover:underline" onClick={() => nav("/baskets")}>
                  Create one on the Baskets page
                </button>{" "}
                (or start from a template), then come back here.
              </p>
            ) : (
              <>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-fg-faint">
                    Draft basket
                  </span>
                  <select
                    className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
                    value={pick}
                    onChange={(e) => setPick(e.target.value)}
                  >
                    <option value="">— choose —</option>
                    {draft.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name} · {b.n_sleeves} sleeves · {b.rebalance_frequency} ·{" "}
                        {inr(b.capital)}
                      </option>
                    ))}
                  </select>
                </label>
                {err && <p className="text-sm text-neg">{err}</p>}
                <div className="flex items-center gap-2">
                  <Button disabled={!pick || deploy.isPending} onClick={onDeploy}>
                    {deploy.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                    Deploy &amp; buy the basket
                  </Button>
                  <Button variant="ghost" onClick={() => setPicking(false)}>
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </div>
        </SectionCard>
      )}

      <SectionCard title="Deployed baskets" bodyClassName="p-0">
        {isLoading ? (
          <p className="p-6 text-center text-sm text-fg-faint">Loading…</p>
        ) : deployed.length === 0 ? (
          <p className="p-6 text-center text-sm text-fg-faint">
            No baskets deployed. Click “Deploy a basket” to forward-test one here.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm tabular-nums">
              <thead>
                <tr className="border-b border-line bg-surface text-fg-faint">
                  <th className="px-3 py-2 text-left">Basket</th>
                  <th className="px-3 py-2 text-right">Value</th>
                  <th className="px-3 py-2 text-right">Return</th>
                  <th className="px-3 py-2 text-right">Invested</th>
                  <th className="px-3 py-2 text-right">Cash</th>
                  <th className="px-3 py-2 text-left">Rebalance</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {deployed.map((b) => (
                  <BasketRow key={b.id} basket={b} onOpen={() => nav(`/baskets/${b.id}`)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function BasketRow({ basket, onOpen }: { basket: Basket; onOpen: () => void }) {
  const { data: st } = useBasketStatus(basket.id);
  const rebalance = useRebalanceBasket(basket.id);
  const undeploy = useUndeployBasket(basket.id);
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (kind: "rebalance" | "undeploy") => {
    setBusy(kind);
    try {
      if (kind === "rebalance") await rebalance.mutateAsync(true);
      else if (confirm(`Undeploy "${basket.name}" and liquidate its positions?`))
        await undeploy.mutateAsync(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <tr className="border-b border-line/60 last:border-0 hover:bg-elevated/40">
      <td className="px-3 py-2 text-left">
        <button className="font-medium text-fg hover:underline" onClick={onOpen}>
          {basket.name}
        </button>
        <div className="text-[11px] text-fg-faint">
          {basket.category ? `${basket.category} · ` : ""}
          {basket.rebalance_frequency}
        </div>
      </td>
      <td className="px-3 py-2 text-right">{st ? inr(st.portfolio_value) : "…"}</td>
      <td
        className={cn(
          "px-3 py-2 text-right font-semibold",
          (st?.return_pct ?? 0) < 0 ? "text-neg" : "text-pos",
        )}
      >
        {st ? pctSigned(st.return_pct ?? null, 2) : "…"}
      </td>
      <td className="px-3 py-2 text-right">{st ? inr(st.invested_value) : "…"}</td>
      <td className="px-3 py-2 text-right">{st ? inr(st.basket_cash) : "…"}</td>
      <td className="px-3 py-2 text-left">
        {st?.rebalance_due ? (
          <span className="rounded bg-amber-400/10 px-1.5 py-0.5 text-[11px] font-semibold text-amber-500">
            due
          </span>
        ) : (
          <span className="text-[11px] text-fg-faint">
            {basket.last_rebalanced_at
              ? new Date(basket.last_rebalanced_at).toLocaleDateString("en-IN")
              : "—"}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <span className="inline-flex gap-2">
          <button
            className="text-xs text-accent hover:underline disabled:opacity-50"
            disabled={!!busy}
            onClick={() => act("rebalance")}
          >
            {busy === "rebalance" ? "…" : "rebalance"}
          </button>
          <button
            className="text-xs text-neg hover:underline disabled:opacity-50"
            disabled={!!busy}
            onClick={() => act("undeploy")}
          >
            {busy === "undeploy" ? "…" : "undeploy"}
          </button>
        </span>
      </td>
    </tr>
  );
}
