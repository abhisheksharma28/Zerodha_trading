"""Deterministic, single-threaded backtest engine.

Runs the exact same BaseStrategy subclass that simulation/paper/live modes
run (see app.strategies.base). Fills are modelled as "fill at the order
instrument's latest close", optionally adjusted by a CostModel that applies
execution slippage
and the full Indian statutory charge stack (see app.backtesting.costs). The
cost model is injected, never referenced by strategy code, so the same run
can be re-priced under different assumptions.
"""

from dataclasses import dataclass, field

from app.backtesting.costs import CostModel
from app.backtesting.diagnostics import RunDiagnostics
from app.strategies.base import Bar, BaseStrategy, StrategyContext


@dataclass
class SimulatedFill:
    bar_timestamp: object
    instrument: str
    transaction_type: str
    quantity: int
    price: float                 # fill price (post-slippage)
    reference_price: float = 0.0  # bar close before slippage
    segment: str = ""
    cost: float = 0.0            # total charges + slippage attributed to this fill
    product: str = "CNC"
    exchange: str = "NSE"


@dataclass
class BacktestRunResult:
    equity_curve: list[tuple[object, float]]
    fills: list[SimulatedFill]
    final_positions: dict[str, int]
    total_costs: float = 0.0
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    diagnostics: RunDiagnostics = field(default_factory=RunDiagnostics)


class BacktestEngine:
    def __init__(
        self,
        strategy_cls: type[BaseStrategy],
        parameters: dict,
        initial_capital: float,
        cost_model: CostModel | None = None,
        *,
        max_gross_exposure: float | None = None,
    ) -> None:
        """``max_gross_exposure`` caps total position notional (Σ|qty·price|)
        at ``multiple × initial_capital`` — the backtest's stand-in for a
        broker margin limit. An order that would breach it is scaled down to
        fit, or rejected if it cannot. ``None`` (default) leaves exposure
        uncapped, preserving the pre-existing behaviour for callers that
        don't opt in. Independently, once mark-to-market equity falls to
        zero the engine stops accepting new orders (ruin halt) so a
        bankrupt book can't keep "trading"."""
        self.strategy_cls = strategy_cls
        self.parameters = parameters
        self.initial_capital = initial_capital
        self.cost_model = cost_model
        self.max_gross_exposure = max_gross_exposure

    def run(self, candles_by_instrument: dict[str, list[Bar]]) -> BacktestRunResult:
        context = StrategyContext(parameters=self.parameters)
        strategy = self.strategy_cls(context)
        strategy.on_start()

        diag = RunDiagnostics(
            instruments=sorted(candles_by_instrument),
            bars_by_instrument={s: len(b) for s, b in candles_by_instrument.items()},
        )
        diag.total_bars = sum(diag.bars_by_instrument.values())

        merged_bars = sorted(
            (bar for bars in candles_by_instrument.values() for bar in bars),
            key=lambda b: b.timestamp,
        )
        if merged_bars:
            diag.first_bar_ts = str(merged_bars[0].timestamp)
            diag.last_bar_ts = str(merged_bars[-1].timestamp)

        cash = self.initial_capital
        positions: dict[str, int] = {}
        last_price: dict[str, float] = {}
        equity_curve: list[tuple[object, float]] = []
        fills: list[SimulatedFill] = []
        total_costs = 0.0
        cost_breakdown: dict[str, float] = {}
        exposure_cap = (
            self.max_gross_exposure * self.initial_capital
            if self.max_gross_exposure is not None and self.initial_capital > 0
            else None
        )

        def gross_exposure() -> float:
            return sum(
                abs(q) * last_price.get(s, 0.0) for s, q in positions.items() if q
            )

        for bar in merged_bars:
            last_price[bar.instrument] = bar.close
            context.positions = dict(positions)

            if diag.ruined:
                # bankrupt book: freeze trading, keep marking positions
                context.drain_pending_orders()
                mtm = sum(
                    qty * last_price.get(inst, 0.0) for inst, qty in positions.items()
                )
                equity_curve.append((bar.timestamp, cash + mtm))
                continue

            strategy.on_bar(bar)

            for order in context.drain_pending_orders():
                diag.orders_submitted += 1
                if order.quantity <= 0:
                    diag.reject("zero/negative quantity")
                    continue
                side = order.transaction_type
                # Fill at the ORDER INSTRUMENT's own latest close, not this
                # bar's close. With a multi-instrument universe the merged bar
                # stream means `bar` often belongs to a different symbol than
                # the order (e.g. a next-day square-off of a leaked position),
                # and using `bar.close` there prices the fill off the wrong
                # stock. For a same-instrument order `last_price[sym]` was just
                # set to `bar.close` above, so single-symbol runs are unchanged.
                ref_price = float(last_price.get(order.tradingsymbol, bar.close))
                if ref_price <= 0:
                    diag.reject("non-positive bar price")
                    continue

                qty = int(order.quantity)
                sym = order.tradingsymbol
                cur = positions.get(sym, 0)
                s = 1 if side == "BUY" else -1

                # --- gross-exposure cap (broker-margin stand-in) ---
                if exposure_cap is not None:
                    added = (abs(cur + s * qty) - abs(cur)) * ref_price
                    if added > 0:
                        headroom = max(0.0, exposure_cap - gross_exposure())
                        head_shares = int(headroom / ref_price)
                        lo, hi = 0, qty
                        while lo < hi:
                            mid = (lo + hi + 1) // 2
                            if (abs(cur + s * mid) - abs(cur)) <= head_shares:
                                lo = mid
                            else:
                                hi = mid - 1
                        if lo < qty:
                            diag.exposure_capped_orders += 1
                            qty = lo
                        if qty <= 0:
                            diag.reject("gross exposure cap")
                            continue

                segment = ""
                fill_price = ref_price
                cost = 0.0
                if self.cost_model is not None:
                    segment = self.cost_model.segment_for(order.product, order.exchange)
                    fill_price = self.cost_model.fill_price_with_slippage(
                        side, ref_price, segment=segment
                    )
                    cb = self.cost_model.charge(
                        side, fill_price, qty, segment, reference_price=ref_price
                    )
                    cost = cb.total
                    for k, v in cb.to_dict().items():
                        cost_breakdown[k] = cost_breakdown.get(k, 0.0) + v

                signed_qty = qty if side == "BUY" else -qty
                cash -= signed_qty * fill_price + cost
                total_costs += cost
                diag.fills += 1
                positions[sym] = cur + signed_qty
                fills.append(
                    SimulatedFill(
                        bar_timestamp=bar.timestamp,
                        instrument=sym,
                        transaction_type=side,
                        quantity=qty,
                        price=fill_price,
                        reference_price=ref_price,
                        segment=segment,
                        cost=cost,
                        product=order.product,
                        exchange=order.exchange,
                    )
                )

            mark_to_market = sum(
                qty * last_price.get(instrument, 0.0) for instrument, qty in positions.items()
            )
            equity = cash + mark_to_market
            equity_curve.append((bar.timestamp, equity))
            if self.initial_capital > 0:
                diag.peak_gross_exposure_pct = max(
                    diag.peak_gross_exposure_pct,
                    gross_exposure() / self.initial_capital * 100.0,
                )
            if equity <= 0 and not diag.ruined:
                diag.ruined = True
                diag.ruin_ts = str(bar.timestamp)

        strategy.on_stop()

        diag.signals = dict(context.signals)

        return BacktestRunResult(
            equity_curve=equity_curve,
            fills=fills,
            final_positions=positions,
            total_costs=total_costs,
            cost_breakdown={k: round(v, 4) for k, v in cost_breakdown.items()},
            diagnostics=diag,
        )
