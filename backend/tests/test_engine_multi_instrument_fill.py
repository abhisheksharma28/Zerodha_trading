"""Regression: in a multi-instrument run a fill must be priced off the ORDER's
instrument, not off whatever bar happened to trigger on_bar.

The merged bar stream feeds bars from every instrument in timestamp order. A
strategy can submit an order for instrument B while processing a bar for
instrument A (classic case: a next-day safety square-off of a position that
leaked overnight). Pricing that fill at `bar.close` would use A's price for a
B trade -- which produced an impossible JIOFIN exit near 796 when JIOFIN was
trading around 250.
"""

from __future__ import annotations

from app.backtesting.engine import BacktestEngine
from app.backtesting.trades import reconstruct_trades
from app.brokers.base import OrderRequest
from app.strategies.base import Bar, BaseStrategy

CHEAP = "CHEAP"
PRICEY = "PRICEY"


class _ShortsCheapWhileSeeingPricey(BaseStrategy):
    """On the 3rd PRICEY bar, open then (next PRICEY bar) close a CHEAP short.

    Both orders are emitted while the current bar belongs to PRICEY, so they
    exercise the cross-instrument pricing path.
    """

    def on_bar(self, bar: Bar) -> None:
        if bar.instrument != PRICEY:
            return
        seen = self.context.signals.get("pricey_bars", 0) + 1
        self.context.note_signal("pricey_bars")
        if seen == 3:
            self.context.submit_order(OrderRequest(
                tradingsymbol=CHEAP, exchange="NSE", transaction_type="SELL",
                order_type="MARKET", quantity=10, product="MIS",
            ))
        elif seen == 4:
            self.context.submit_order(OrderRequest(
                tradingsymbol=CHEAP, exchange="NSE", transaction_type="BUY",
                order_type="MARKET", quantity=10, product="MIS",
            ))


def _bars(prices, sym):
    return [
        Bar(timestamp=f"2026-04-{i + 1:02d}T09:15:00+05:30", open=p, high=p, low=p,
            close=p, volume=1000, instrument=sym)
        for i, p in enumerate(prices)
    ]


def test_cross_instrument_fill_uses_order_instrument_price():
    cheap = _bars([250, 251, 252, 253, 254, 255], CHEAP)
    pricey = _bars([800, 801, 802, 803, 804, 805], PRICEY)

    res = BacktestEngine(_ShortsCheapWhileSeeingPricey, {}, 1_000_000).run(
        {PRICEY: pricey, CHEAP: cheap}
    )

    cheap_fills = [f for f in res.fills if f.instrument == CHEAP]
    assert len(cheap_fills) == 2
    # Both fills must be near CHEAP's own price band (~250), never PRICEY's ~800.
    for f in cheap_fills:
        assert 240 <= f.price <= 260, f"fill priced off the wrong instrument: {f.price}"

    trades = reconstruct_trades(cheap_fills)
    assert len(trades) == 1
    assert trades[0].direction == "short"
    # A ~1-point adverse move on 10 shares, not a ~550-point blowup.
    assert abs(trades[0].net_pnl) < 100
