import { useState } from "react";

import type { PaperHolding, PaperOrder, PaperPosition, PaperStrategyRun } from "@/api/paperAccount";
import { DataTable, type Column } from "@/components/DataTable";
import { AlgoPanel, AlgoPill } from "@/components/paper/AlgoPanel";
import { BasketGroupedHoldings } from "@/components/paper/BasketGroupedHoldings";
import { DeployedBaskets } from "@/components/paper/DeployedBaskets";
import { OrderPad, type OrderPadInit } from "@/components/paper/OrderPad";
import { StrategyDeploy } from "@/components/paper/StrategyDeploy";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useAddFunds,
  useCancelOrder,
  useRetryOrder,
  useDeletePaperStrategy,
  useExitPosition,
  usePaperAlgo,
  usePaperHoldings,
  usePaperLedger,
  usePaperOrders,
  usePaperPositions,
  usePaperStrategyRuns,
  usePaperSummary,
  usePaperTrades,
  useReconcilePaper,
  useResetPaper,
  useSetPaperStrategyStatus,
} from "@/hooks/usePaperAccount";
import { inr, num, pctSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = ["Holdings", "Positions", "Orders", "Algo", "Strategies", "Baskets", "Funds"] as const;
const pnlTone = (v: number | null | undefined) =>
  (v ?? 0) > 0 ? "text-pos" : (v ?? 0) < 0 ? "text-neg" : "text-fg-muted";

const SOURCE_CLS: Record<string, string> = {
  manual: "bg-elevated text-fg-muted",
  algo: "bg-amber-400/15 text-amber-500",
  strategy: "bg-violet-500/15 text-violet-400",
  basket: "bg-[#4184f3]/15 text-[#4184f3]",
  squareoff: "bg-neg/10 text-neg",
};

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data;
  return d?.message ?? d?.detail ?? fallback;
}

function RetryOrderButton({ orderId }: { orderId: string }) {
  const retry = useRetryOrder();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-1.5">
      {msg && <span className="max-w-[220px] truncate text-[10px] text-neg" title={msg}>{msg}</span>}
      <button
        type="button"
        disabled={retry.isPending}
        onClick={() => {
          setMsg(null);
          retry.mutate(orderId, {
            onSuccess: (o) => {
              if (o.status === "REJECTED") setMsg(o.status_message ?? "Rejected again.");
            },
            onError: (e) => setMsg(errMsg(e, "Retry failed.")),
          });
        }}
        className="rounded border border-accent/50 px-1.5 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft disabled:opacity-50"
      >
        {retry.isPending ? "…" : "Retry"}
      </button>
    </span>
  );
}

function SourceBadge({ source, label }: { source: string; label: string }) {
  return (
    <span
      className={cn(
        "inline-block max-w-[220px] truncate rounded px-1.5 py-0.5 text-[10px] font-semibold",
        SOURCE_CLS[source] ?? SOURCE_CLS.manual,
      )}
      title={label}
    >
      {label}
    </span>
  );
}

function Stat({
  label,
  value,
  tone,
  sub,
}: {
  label: string;
  value: string;
  tone?: string;
  sub?: string;
}) {
  return (
    <div className="min-w-[8rem] flex-1 border-r border-line px-4 py-2 last:border-0">
      <p className="text-[11px] uppercase tracking-wide text-fg-faint">{label}</p>
      <p className={cn("mt-0.5 text-lg font-semibold tabular-nums", tone)}>{value}</p>
      {sub && <p className="text-[11px] text-fg-faint">{sub}</p>}
    </div>
  );
}

export default function PaperTradingPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Holdings");
  const [pad, setPad] = useState<{ open: boolean; init: OrderPadInit }>({ open: false, init: {} });
  const openPad = (init: OrderPadInit = {}) => setPad({ open: true, init });

  const [deploying, setDeploying] = useState(false);
  const { data: sm } = usePaperSummary();
  const { data: positions = [] } = usePaperPositions();
  const { data: holdings = [] } = usePaperHoldings();
  const { data: orders = [] } = usePaperOrders();
  const { data: trades = [] } = usePaperTrades();
  const { data: ledger = [] } = usePaperLedger();
  const { data: strategyRuns = [] } = usePaperStrategyRuns();
  const { data: algo } = usePaperAlgo();
  const exitPos = useExitPosition();
  const cancelOrder = useCancelOrder();
  const addFunds = useAddFunds();
  const reset = useResetPaper();
  const reconcile = useReconcilePaper();
  const setStratStatus = useSetPaperStrategyStatus();
  const deleteStrat = useDeletePaperStrategy();

  const dayPnl = (sm?.pnl.positions_unrealized ?? 0) + (sm?.pnl.holdings_day ?? 0) + (sm?.pnl.booked ?? 0);

  const holdCols: Column<PaperHolding>[] = [
    { key: "sym", header: "Instrument", cell: (h) => <span className="font-medium text-fg">{h.tradingsymbol}</span>, sortValue: (h) => h.tradingsymbol },
    { key: "qty", header: "Qty", align: "right", cell: (h) => <span className="tabular-nums">{h.qty}{h.t1_qty ? ` (T1 ${h.t1_qty})` : ""}</span>, sortValue: (h) => h.qty },
    { key: "avg", header: "Avg", align: "right", cell: (h) => <span className="tabular-nums">{num(h.avg_price, 2)}</span>, sortValue: (h) => h.avg_price },
    { key: "ltp", header: "LTP", align: "right", cell: (h) => <span className="tabular-nums">{h.ltp == null ? "—" : num(h.ltp, 2)}</span>, sortValue: (h) => h.ltp },
    { key: "cur", header: "Cur. value", align: "right", cell: (h) => <span className="tabular-nums">{inr(h.current_value)}</span>, sortValue: (h) => h.current_value },
    { key: "pnl", header: "P&L", align: "right", cell: (h) => <span className={cn("tabular-nums font-medium", pnlTone(h.pnl))}>{pctSigned(h.pnl_pct)} · {inr(h.pnl)}</span>, sortValue: (h) => h.pnl },
    { key: "day", header: "Day", align: "right", cell: (h) => <span className={cn("tabular-nums", pnlTone(h.day_change_pct))}>{pctSigned(h.day_change_pct)}</span>, sortValue: (h) => h.day_change_pct },
    {
      key: "act",
      header: "",
      align: "right",
      cell: (h) => (
        <div className="flex justify-end gap-1">
          <button type="button" onClick={() => openPad({ ref: `${h.exchange}:${h.tradingsymbol}`, side: "BUY", product: "CNC" })} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-[#4184f3] hover:bg-[#4184f3]/10">Buy</button>
          <button type="button" onClick={() => openPad({ ref: `${h.exchange}:${h.tradingsymbol}`, side: "SELL", product: "CNC", qty: h.qty })} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-[#ff5722] hover:bg-[#ff5722]/10">Sell</button>
        </div>
      ),
    },
  ];

  const posCols: Column<PaperPosition>[] = [
    { key: "sym", header: "Instrument", cell: (p) => <span className="font-medium text-fg">{p.tradingsymbol}</span>, sortValue: (p) => p.tradingsymbol },
    { key: "prod", header: "Product", cell: (p) => <Badge variant="default" className="text-[10px]">{p.product}</Badge>, sortValue: (p) => p.product },
    { key: "qty", header: "Qty", align: "right", cell: (p) => <span className={cn("tabular-nums", p.net_qty < 0 && "text-neg")}>{p.net_qty}</span>, sortValue: (p) => p.net_qty },
    { key: "avg", header: "Avg", align: "right", cell: (p) => <span className="tabular-nums">{num(p.avg_price, 2)}</span>, sortValue: (p) => p.avg_price },
    { key: "ltp", header: "LTP", align: "right", cell: (p) => <span className="tabular-nums">{p.ltp == null ? "—" : num(p.ltp, 2)}</span>, sortValue: (p) => p.ltp },
    { key: "chg", header: "Chg", align: "right", cell: (p) => <span className={cn("tabular-nums", pnlTone(p.day_change_pct))}>{pctSigned(p.day_change_pct)}</span>, sortValue: (p) => p.day_change_pct },
    { key: "pnl", header: "P&L", align: "right", cell: (p) => <span className={cn("tabular-nums font-semibold", pnlTone(p.pnl))}>{inr(p.pnl)}</span>, sortValue: (p) => p.pnl },
    {
      key: "act",
      header: "",
      align: "right",
      cell: (p) => (
        <div className="flex justify-end gap-1">
          <button type="button" onClick={() => openPad({ ref: `${p.exchange}:${p.tradingsymbol}`, side: p.net_qty >= 0 ? "BUY" : "SELL", product: p.product })} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-fg-muted hover:bg-elevated">Add</button>
          <button type="button" onClick={() => exitPos.mutate(p.id)} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-[#ff5722] hover:bg-[#ff5722]/10">Exit</button>
        </div>
      ),
    },
  ];

  const stratCols: Column<PaperStrategyRun>[] = [
    { key: "name", header: "Strategy", cell: (r) => (<span><span className="font-medium text-fg">{r.name}</span><span className="ml-1 text-[11px] text-fg-faint">{r.slug}</span></span>), sortValue: (r) => r.name },
    { key: "inst", header: "Instruments", cell: (r) => <span className="text-fg-muted">{r.instruments.map((i) => i.split(":")[1]).join(", ")}</span>, sortValue: (r) => r.instruments.length },
    { key: "tf", header: "TF · Prod", cell: (r) => <span className="text-fg-muted">{r.timeframe} · {r.product}</span>, sortValue: (r) => r.timeframe },
    { key: "trd", header: "Trades", align: "right", cell: (r) => <span className="tabular-nums">{r.trades}</span>, sortValue: (r) => r.trades },
    { key: "exp", header: "Exposure", align: "right", cell: (r) => <span className="tabular-nums text-fg-faint">{Object.entries(r.open_exposure).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ") || "flat"}</span>, sortValue: (r) => Object.keys(r.open_exposure).length },
    { key: "pnl", header: "Realised P&L", align: "right", cell: (r) => <span className={cn("tabular-nums font-medium", pnlTone(r.realized_pnl))}>{inr(r.realized_pnl)}</span>, sortValue: (r) => r.realized_pnl },
    {
      key: "status",
      header: "Status",
      cell: (r) => (
        <span className="flex items-center gap-2">
          <Badge variant={r.status === "ACTIVE" ? "success" : r.status === "PAUSED" ? "warning" : "default"} className="text-[10px]">
            {r.status}
          </Badge>
          {r.error && <span className="text-[11px] text-neg" title={r.error}>error</span>}
        </span>
      ),
      sortValue: (r) => r.status,
    },
    {
      key: "act",
      header: "",
      align: "right",
      cell: (r) => (
        <div className="flex justify-end gap-1">
          {r.status !== "STOPPED" && (
            <button type="button" onClick={() => setStratStatus.mutate({ id: r.id, status: r.status === "ACTIVE" ? "PAUSED" : "ACTIVE" })} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-fg-muted hover:bg-elevated">
              {r.status === "ACTIVE" ? "Pause" : "Resume"}
            </button>
          )}
          {r.status !== "STOPPED" && (
            <button type="button" onClick={() => setStratStatus.mutate({ id: r.id, status: "STOPPED" })} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-[#ff5722] hover:bg-[#ff5722]/10">
              Stop
            </button>
          )}
          {r.status === "STOPPED" && (
            <button type="button" onClick={() => window.confirm("Remove this stopped strategy from the list?") && deleteStrat.mutate(r.id)} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-fg-faint hover:bg-elevated">
              Delete
            </button>
          )}
        </div>
      ),
    },
  ];

  const orderCols: Column<PaperOrder>[] = [
    { key: "time", header: "Time", cell: (o) => <span className="tabular-nums text-fg-faint">{o.placed_at ? new Date(o.placed_at).toLocaleTimeString("en-IN") : "—"}</span>, sortValue: (o) => o.placed_at ?? "" },
    {
      key: "sym",
      header: "Instrument",
      cell: (o) => <span className="font-medium text-fg">{o.tradingsymbol}</span>,
      sortValue: (o) => o.tradingsymbol,
    },
    {
      key: "source",
      header: "Source",
      cell: (o) => <SourceBadge source={o.source} label={o.source_label} />,
      sortValue: (o) => o.source_label,
    },
    { key: "side", header: "Side", cell: (o) => <span className={cn("text-xs font-bold", o.side === "BUY" ? "text-[#4184f3]" : "text-[#ff5722]")}>{o.side}</span>, sortValue: (o) => o.side },
    { key: "type", header: "Type", cell: (o) => <span className="text-fg-muted">{o.order_type} · {o.product}</span>, sortValue: (o) => o.order_type },
    { key: "qty", header: "Qty", align: "right", cell: (o) => <span className="tabular-nums">{o.filled_qty}/{o.quantity}</span>, sortValue: (o) => o.quantity },
    { key: "px", header: "Price", align: "right", cell: (o) => <span className="tabular-nums">{o.avg_fill_price ? num(o.avg_fill_price, 2) : o.price ? num(o.price, 2) : "MKT"}</span>, sortValue: (o) => o.avg_fill_price ?? o.price ?? 0 },
    {
      key: "status",
      header: "Status",
      cell: (o) => (
        <span className="flex items-center gap-2">
          <Badge variant={o.status === "COMPLETE" ? "success" : o.status === "REJECTED" ? "destructive" : o.status === "OPEN" ? "warning" : "default"} className="text-[10px]">
            {o.status}
          </Badge>
          {o.status_message && <span className="text-[11px] text-fg-faint">{o.status_message}</span>}
        </span>
      ),
      sortValue: (o) => o.status,
    },
    {
      key: "act",
      header: "",
      align: "right",
      cell: (o) =>
        o.status === "OPEN" ? (
          <button type="button" onClick={() => cancelOrder.mutate(o.id)} className="rounded px-1.5 py-0.5 text-[11px] font-medium text-[#ff5722] hover:bg-[#ff5722]/10">Cancel</button>
        ) : o.status === "REJECTED" || o.status === "CANCELLED" ? (
          <RetryOrderButton orderId={o.id} />
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Paper Trading"
        subtitle="A demo trading account — virtual funds, real live prices. Buy / sell equity and F&O; positions mark to the tape."
        actions={
          <div className="flex items-center gap-2">
            <AlgoPill status={algo} />
            <Button size="sm" onClick={() => openPad({})} className="bg-[#4184f3] hover:bg-[#356fd0]">
              + New order
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const v = window.prompt("Add virtual funds (₹). Use a negative number to withdraw.", "100000");
                if (v && Number(v)) addFunds.mutate(Number(v));
              }}
            >
              Add funds
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={reconcile.isPending}
              title="Rebuild cash & holdings from the trade log (fixes drift, keeps history)"
              onClick={() =>
                reconcile.mutate(undefined, {
                  onSuccess: (r) =>
                    window.alert(
                      `Reconciled. Cash ₹${Math.round(r.old_cash).toLocaleString("en-IN")} → ₹${Math.round(
                        r.new_cash,
                      ).toLocaleString("en-IN")} (Δ ₹${Math.round(r.delta).toLocaleString("en-IN")}).\n\n${r.note}`,
                    ),
                })
              }
            >
              {reconcile.isPending ? "Reconciling…" : "Reconcile"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                if (window.confirm("Reset the paper account? All positions, holdings, orders and P&L are wiped.")) reset.mutate(undefined);
              }}
            >
              Reset
            </Button>
          </div>
        }
      />

      {/* Kite-style equity strip */}
      <div className="flex flex-wrap items-stretch rounded-lg border border-line bg-surface">
        <Stat label="Available margin" value={inr(sm?.funds.available_margin ?? 0)} />
        <Stat label="Used margin" value={inr(sm?.funds.used_margin ?? 0)} />
        <Stat
          label="P&L (day)"
          value={inr(dayPnl)}
          tone={pnlTone(dayPnl)}
          sub={sm?.pnl.total_pct != null ? `${pctSigned(sm.pnl.total_pct)} total` : undefined}
        />
        <Stat
          label="Total P&L"
          value={inr(sm?.pnl.total ?? 0)}
          tone={pnlTone(sm?.pnl.total)}
          sub={`booked ${inr(sm?.pnl.booked ?? 0)}`}
        />
        <Stat label="Net worth" value={inr(sm?.net_worth ?? 0)} sub={`invested ${inr(sm?.account.invested_capital ?? 0)}`} />
      </div>

      {/* sub-tabs */}
      <div className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-xs font-medium",
              t === tab ? "border-b-2 border-accent text-fg" : "text-fg-muted hover:text-fg",
            )}
          >
            {t}
            {t === "Holdings" && ` (${holdings.length})`}
            {t === "Positions" && ` (${positions.length})`}
            {t === "Orders" && ` (${orders.filter((o) => o.status === "OPEN").length})`}
            {t === "Algo" && algo?.config.enabled && " ●"}
            {t === "Strategies" && ` (${strategyRuns.filter((r) => r.status === "ACTIVE").length})`}
          </button>
        ))}
      </div>

      {tab === "Holdings" && <BasketGroupedHoldings holdings={holdings} columns={holdCols} />}

      {tab === "Positions" && (
        <SectionCard title="Positions" bodyClassName="p-0">
          <DataTable columns={posCols} rows={positions} rowKey={(p) => p.id} searchable searchPlaceholder="Filter positions…" empty="No open positions. Place an MIS / NRML order to open one." />
        </SectionCard>
      )}

      {tab === "Orders" && (
        <SectionCard title="Order book" bodyClassName="p-0">
          <DataTable columns={orderCols} rows={orders} rowKey={(o) => o.id} searchable searchPlaceholder="Filter orders…" initialSort={{ key: "time", dir: "desc" }} empty="No orders yet." />
        </SectionCard>
      )}

      {tab === "Algo" && <AlgoPanel />}

      {tab === "Strategies" && (
        <div className="flex flex-col gap-4">
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setDeploying((v) => !v)}>
              {deploying ? "Close" : "+ Deploy strategy"}
            </Button>
          </div>
          {deploying && <StrategyDeploy onDone={() => setDeploying(false)} />}
          <SectionCard title="Deployed strategies" bodyClassName="p-0">
            <DataTable
              columns={stratCols}
              rows={strategyRuns}
              rowKey={(r) => r.id}
              empty="No strategies deployed. Click ‘Deploy strategy’ to run a library template in this account."
            />
          </SectionCard>
        </div>
      )}

      {tab === "Baskets" && <DeployedBaskets />}

      {tab === "Funds" && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Available" value={inr(sm?.funds.available_margin ?? 0)} />
            <Stat label="Used margin" value={inr(sm?.funds.used_margin ?? 0)} />
            <Stat label="Opening balance" value={inr(sm?.account.opening_balance ?? 0)} />
            <Stat label="Charges paid" value={inr(sm?.charges_paid ?? 0)} tone="text-neg" />
          </div>
          <SectionCard title="Funds statement" bodyClassName="p-0">
            <DataTable
              columns={[
                { key: "at", header: "Time", cell: (r) => <span className="tabular-nums text-fg-faint">{r.at ? new Date(r.at).toLocaleString("en-IN") : "—"}</span>, sortValue: (r) => r.at ?? "" },
                { key: "kind", header: "Type", cell: (r) => <span className="text-fg-muted">{r.kind}</span>, sortValue: (r) => r.kind },
                { key: "note", header: "Note", cell: (r) => <span className="text-fg-muted">{r.note}</span>, sortValue: (r) => r.note ?? "" },
                { key: "amt", header: "Amount", align: "right", cell: (r) => <span className={cn("tabular-nums", pnlTone(r.amount))}>{inr(r.amount)}</span>, sortValue: (r) => r.amount },
                { key: "bal", header: "Balance", align: "right", cell: (r) => <span className="tabular-nums">{inr(r.balance_after)}</span>, sortValue: (r) => r.balance_after },
              ]}
              rows={ledger}
              rowKey={(r) => r.id}
              empty="No ledger entries."
            />
          </SectionCard>
          <SectionCard title="Trade book" bodyClassName="p-0">
            <DataTable
              columns={[
                { key: "at", header: "Time", cell: (t) => <span className="tabular-nums text-fg-faint">{t.traded_at ? new Date(t.traded_at).toLocaleTimeString("en-IN") : "—"}</span>, sortValue: (t) => t.traded_at ?? "" },
                { key: "sym", header: "Instrument", cell: (t) => <span className="font-medium text-fg">{t.tradingsymbol}</span>, sortValue: (t) => t.tradingsymbol },
                { key: "source", header: "Source", cell: (t) => <SourceBadge source={t.source} label={t.source_label} />, sortValue: (t) => t.source_label },
                { key: "side", header: "Side", cell: (t) => <span className={cn("text-xs font-bold", t.side === "BUY" ? "text-[#4184f3]" : "text-[#ff5722]")}>{t.side}</span>, sortValue: (t) => t.side },
                { key: "qty", header: "Qty", align: "right", cell: (t) => <span className="tabular-nums">{t.quantity}</span>, sortValue: (t) => t.quantity },
                { key: "px", header: "Price", align: "right", cell: (t) => <span className="tabular-nums">{num(t.price, 2)}</span>, sortValue: (t) => t.price },
                { key: "chg", header: "Charges", align: "right", cell: (t) => <span className="tabular-nums text-neg">{inr(t.charges)}</span>, sortValue: (t) => t.charges },
                { key: "pnl", header: "Realised", align: "right", cell: (t) => <span className={cn("tabular-nums", pnlTone(t.realized_pnl))}>{t.realized_pnl ? inr(t.realized_pnl) : "—"}</span>, sortValue: (t) => t.realized_pnl },
              ]}
              rows={trades}
              rowKey={(t) => t.id}
              initialSort={{ key: "at", dir: "desc" }}
              empty="No trades yet."
            />
          </SectionCard>
        </div>
      )}

      <p className="text-[11px] text-fg-faint">
        Fills are modelled at the live last-traded price with the Indian statutory cost stack. Margins
        are estimates. MIS positions auto-square-off at 15:20 IST. Nothing here places a real order.
      </p>

      <OrderPad open={pad.open} init={pad.init} onClose={() => setPad({ open: false, init: {} })} />
    </div>
  );
}
