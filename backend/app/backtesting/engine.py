"""Deterministic, single-threaded backtest engine.

Runs the exact same BaseStrategy subclass that simulation/paper/live modes
run (see app.strategies.base). Fills are modelled as "fill at this bar's
close", optionally adjusted by a CostModel that applies execution slippage
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
    ) -> None:
        self.strategy_cls = strategy_cls
        self.parameters = parameters
        self.initial_capital = initial_capital
        self.cost_model = cost_model

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

        for bar in merged_bars:
            last_price[bar.instrument] = bar.close
            context.positions = dict(positions)

            strategy.on_bar(bar)

            for order in context.drain_pending_orders():
                diag.orders_submitted += 1
                if order.quantity <= 0:
                    diag.reject("zero/negative quantity")
                    continue
                ref_price = float(bar.close)
                side = order.transaction_type
                if ref_price <= 0:
                    diag.reject("non-positive bar price")
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
                        side, fill_price, order.quantity, segment, reference_price=ref_price
                    )
                    cost = cb.total
                    for k, v in cb.to_dict().items():
                        cost_breakdown[k] = cost_breakdown.get(k, 0.0) + v

                signed_qty = order.quantity if side == "BUY" else -order.quantity
                cash -= signed_qty * fill_price + cost
                total_costs += cost
                diag.fills += 1
                positions[order.tradingsymbol] = positions.get(order.tradingsymbol, 0) + signed_qty
                fills.append(
                    SimulatedFill(
                        bar_timestamp=bar.timestamp,
                        instrument=order.tradingsymbol,
                        transaction_type=side,
                        quantity=order.quantity,
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
            equity_curve.append((bar.timestamp, cash + mark_to_market))

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
