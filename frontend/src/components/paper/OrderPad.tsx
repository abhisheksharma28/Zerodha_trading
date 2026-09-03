import { useEffect, useMemo, useState } from "react";

import type { OrderType, Product, Side } from "@/api/paperAccount";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { usePaperInstrument, usePlaceOrder } from "@/hooks/usePaperAccount";
import { inr, num } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface OrderPadInit {
  ref?: string | null;
  side?: Side;
  product?: Product;
  qty?: number;
}

const PRODUCTS_EQ: Product[] = ["CNC", "MIS"];
const PRODUCTS_FNO: Product[] = ["NRML", "MIS"];
const TYPES: OrderType[] = ["MARKET", "LIMIT", "SL", "SL-M"];

// rough margin estimate mirroring the backend, just for the preview
function estMargin(assetClass: string, product: Product, side: Side, price: number, qty: number): number {
  const notional = price * qty;
  if (assetClass === "OPT") return side === "BUY" ? notional : notional * 0.16;
  if (assetClass === "FUT") return notional * 0.16;
  if (product === "MIS") return notional * 0.2;
  return notional;
}

export function OrderPad({
  open,
  init,
  onClose,
}: {
  open: boolean;
  init: OrderPadInit;
  onClose: () => void;
}) {
  const [ref, setRef] = useState<string | null>(init.ref ?? null);
  const [side, setSide] = useState<Side>(init.side ?? "BUY");
  const [product, setProduct] = useState<Product>(init.product ?? "CNC");
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [qty, setQty] = useState<number>(init.qty ?? 1);
  const [price, setPrice] = useState<string>("");
  const [trigger, setTrigger] = useState<string>("");
  const place = usePlaceOrder();
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setRef(init.ref ?? null);
    setSide(init.side ?? "BUY");
    setProduct(init.product ?? "CNC");
    setOrderType("MARKET");
    setQty(init.qty ?? 1);
    setPrice("");
    setTrigger("");
    setErr(null);
    setDone(null);
  }, [open, init]);

  const inst = usePaperInstrument(open ? ref : null);
  const info = inst.data;
  const isFno = info?.asset_class === "FUT" || info?.asset_class === "OPT";
  const products = isFno ? PRODUCTS_FNO : PRODUCTS_EQ;
  const lot = info?.lot_size ?? 1;
  // qty actually sent: F&O rounds to whole lots
  const effQty = isFno && lot > 1 ? Math.max(lot, Math.round(qty / lot) * lot) : qty;
  const effProduct = isFno && !products.includes(product) ? "NRML" : product;

  const refPx = useMemo(() => {
    const p = orderType === "LIMIT" || orderType === "SL" ? Number(price) : info?.ltp ?? 0;
    return Number.isFinite(p) && p > 0 ? p : info?.ltp ?? 0;
  }, [orderType, price, info?.ltp]);

  const margin = info ? estMargin(info.asset_class, effProduct, side, refPx, effQty) : 0;
  const orderValue = refPx * effQty;
  const charges = Math.max(20, 0.0004 * orderValue) + (side === "SELL" ? 0.001 * orderValue : 0);

  const submit = () => {
    setErr(null);
    if (!ref || !info?.found) {
      setErr("Pick an instrument first.");
      return;
    }
    place.mutate(
      {
        exchange: info.exchange,
        tradingsymbol: info.tradingsymbol,
        side,
        quantity: effQty,
        order_type: orderType,
        product: effProduct,
        price: orderType === "LIMIT" || orderType === "SL" ? Number(price) || null : null,
        trigger_price: orderType === "SL" || orderType === "SL-M" ? Number(trigger) || null : null,
      },
      {
        onSuccess: (o) => {
          if (o.status === "REJECTED") setErr(o.status_message ?? "Order rejected.");
          else setDone(`${o.status}: ${o.side} ${o.quantity} ${o.tradingsymbol}` + (o.avg_fill_price ? ` @ ${num(o.avg_fill_price, 2)}` : " (resting)"));
        },
        onError: (e: unknown) => setErr((e as { message?: string })?.message ?? "Order failed."),
      },
    );
  };

  if (!open) return null;
  const buy = side === "BUY";
  const accent = buy ? "bg-[#4184f3]" : "bg-[#ff5722]";
  const accentText = buy ? "text-[#4184f3]" : "text-[#ff5722]";

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[420px] flex-col bg-surface shadow-2xl">
        {/* header */}
        <div className={cn("flex items-center justify-between px-4 py-3 text-white", accent)}>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">
              {info?.tradingsymbol ?? "Select instrument"}{" "}
              <span className="opacity-80">{info?.exchange}</span>
            </p>
            <p className="text-xs opacity-90">
              {info?.ltp != null ? `LTP ${num(info.ltp, 2)}` : "—"}
              {info?.prev_close != null && info?.ltp != null && (
                <span className="ml-2">
                  {info.ltp - info.prev_close >= 0 ? "+" : ""}
                  {num(((info.ltp - info.prev_close) / info.prev_close) * 100, 2)}%
                </span>
              )}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-lg leading-none hover:bg-white/20">
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {/* BUY / SELL toggle */}
          <div className="mb-3 flex overflow-hidden rounded-md border border-line">
            {(["BUY", "SELL"] as Side[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSide(s)}
                className={cn(
                  "flex-1 py-1.5 text-sm font-semibold transition-colors",
                  side === s
                    ? s === "BUY"
                      ? "bg-[#4184f3] text-white"
                      : "bg-[#ff5722] text-white"
                    : "bg-elevated text-fg-muted",
                )}
              >
                {s}
              </button>
            ))}
          </div>

          {!init.ref && (
            <div className="mb-3">
              <InstrumentSearch
                value={ref ? [ref] : []}
                onChange={(next) => setRef(next[next.length - 1] ?? null)}
                multiple={false}
                placeholder="Search stock / future / option…"
              />
            </div>
          )}

          {/* product */}
          <div className="mb-3 flex gap-2">
            {products.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setProduct(p)}
                className={cn(
                  "flex-1 rounded-md border px-2 py-1.5 text-xs font-medium",
                  product === p ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted",
                )}
              >
                {p === "CNC" ? "CNC · delivery" : p === "MIS" ? "MIS · intraday" : "NRML · carry"}
              </button>
            ))}
          </div>

          {/* qty + price */}
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs">
              <span className="text-fg-faint">Qty {isFno && lot > 1 ? `(×${lot})` : ""}</span>
              <input
                type="number"
                min={isFno ? lot : 1}
                step={isFno ? lot : 1}
                value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
                className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm tabular-nums"
              />
            </label>
            <label className="text-xs">
              <span className="text-fg-faint">Price</span>
              <input
                type="number"
                step="0.05"
                disabled={orderType === "MARKET" || orderType === "SL-M"}
                value={orderType === "MARKET" || orderType === "SL-M" ? "" : price}
                placeholder={orderType === "MARKET" || orderType === "SL-M" ? "at market" : ""}
                onChange={(e) => setPrice(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm tabular-nums disabled:opacity-50"
              />
            </label>
          </div>

          {/* order type */}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setOrderType(t)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium",
                  orderType === t ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {(orderType === "SL" || orderType === "SL-M") && (
            <label className="mt-3 block text-xs">
              <span className="text-fg-faint">Trigger price</span>
              <input
                type="number"
                step="0.05"
                value={trigger}
                onChange={(e) => setTrigger(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm tabular-nums"
              />
            </label>
          )}

          {/* preview */}
          <div className="mt-4 rounded-md border border-line bg-elevated/50 p-2.5 text-xs">
            <div className="flex justify-between">
              <span className="text-fg-faint">Order value</span>
              <span className="tabular-nums">{inr(orderValue)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-fg-faint">Margin required (est.)</span>
              <span className="tabular-nums">{inr(margin)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-fg-faint">Charges (est.)</span>
              <span className="tabular-nums">≈ {inr(charges)}</span>
            </div>
          </div>

          {err && <p className="mt-3 rounded bg-neg/10 px-2 py-1.5 text-xs text-neg">{err}</p>}
          {done && <p className="mt-3 rounded bg-pos/10 px-2 py-1.5 text-xs text-pos">{done}</p>}
        </div>

        {/* action bar */}
        <div className="border-t border-line p-3">
          <button
            type="button"
            onClick={submit}
            disabled={place.isPending || !info?.found}
            className={cn(
              "w-full rounded-md py-2.5 text-sm font-semibold text-white disabled:opacity-60",
              accent,
            )}
          >
            {place.isPending ? "Placing…" : `${side} ${info?.tradingsymbol ?? ""}`.trim()}
          </button>
          <p className={cn("mt-1.5 text-center text-[11px]", accentText)}>
            Paper trade — virtual funds, live prices. Not a real order.
          </p>
        </div>
      </div>
    </>
  );
}
