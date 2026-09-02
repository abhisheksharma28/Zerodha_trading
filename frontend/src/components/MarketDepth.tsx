const num = (v: unknown, d = 2) =>
  typeof v === "number" && isFinite(v)
    ? v.toLocaleString("en-IN", { maximumFractionDigits: d })
    : "N/A";

export type DepthLevel = { price: number; quantity: number; orders: number };

export function MarketDepth({
  buy,
  sell,
  totalBuy,
  totalSell,
}: {
  buy: DepthLevel[];
  sell: DepthLevel[];
  totalBuy?: number | null;
  totalSell?: number | null;
}) {
  const max = Math.max(1, ...buy.map((b) => b.quantity), ...sell.map((s) => s.quantity));
  const rows = Math.max(buy.length, sell.length, 5);
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 text-[11px] tabular-nums">
        <div>
          <div className="mb-0.5 flex justify-between text-fg-faint">
            <span>Qty</span>
            <span>Bid</span>
          </div>
          {Array.from({ length: rows }).map((_, i) => {
            const b = buy[i];
            return (
              <div key={i} className="relative flex justify-between px-1 py-0.5">
                {b && (
                  <span
                    className="absolute inset-y-0 right-0 bg-pos/15"
                    style={{ width: `${(b.quantity / max) * 100}%` }}
                  />
                )}
                <span className="relative">{b ? num(b.quantity, 0) : "–"}</span>
                <span className="relative text-pos">{b ? num(b.price) : ""}</span>
              </div>
            );
          })}
        </div>
        <div>
          <div className="mb-0.5 flex justify-between text-fg-faint">
            <span>Ask</span>
            <span>Qty</span>
          </div>
          {Array.from({ length: rows }).map((_, i) => {
            const s = sell[i];
            return (
              <div key={i} className="relative flex justify-between px-1 py-0.5">
                {s && (
                  <span
                    className="absolute inset-y-0 left-0 bg-neg/15"
                    style={{ width: `${(s.quantity / max) * 100}%` }}
                  />
                )}
                <span className="relative text-neg">{s ? num(s.price) : ""}</span>
                <span className="relative">{s ? num(s.quantity, 0) : "–"}</span>
              </div>
            );
          })}
        </div>
      </div>
      {(totalBuy != null || totalSell != null) && (
        <div className="mt-1 flex justify-between text-[11px] text-fg-faint">
          <span>Total bid {num(totalBuy, 0)}</span>
          <span>Total ask {num(totalSell, 0)}</span>
        </div>
      )}
    </div>
  );
}
