"""Deterministic, single-threaded backtest engine.

Runs the exact same BaseStrategy subclass that simulation/paper/live modes
run (see app.strategies.base) — the only mode-specific piece is fill
simulation, done here with an idealized "fill at this bar's close" model.
More realistic fill modelling (slippage, next-bar-open fills, partial fills)
is a natural follow-up; this is intentionally the simplest model that is
still honest about being idealized rather than pretending precision it
doesn't have.
"""

from dataclasses import dataclass

from app.strategies.base import Bar, BaseStrategy, StrategyContext


@dataclass
class SimulatedFill:
    bar_timestamp: object
    instrument: str
    transaction_type: str
    quantity: int
    price: float


@dataclass
class BacktestRunResult:
    equity_curve: list[tuple[object, float]]
    fills: list[SimulatedFill]
    final_positions: dict[str, int]


class BacktestEngine:
    def __init__(self, strategy_cls: type[BaseStrategy], parameters: dict, initial_capital: float) -> None:
        self.strategy_cls = strategy_cls
        self.parameters = parameters
        self.initial_capital = initial_capital

    def run(self, candles_by_instrument: dict[str, list[Bar]]) -> BacktestRunResult:
        context = StrategyContext(parameters=self.parameters)
        strategy = self.strategy_cls(context)
        strategy.on_start()

        merged_bars = sorted(
            (bar for bars in candles_by_instrument.values() for bar in bars),
            key=lambda b: b.timestamp,
        )

        cash = self.initial_capital
        positions: dict[str, int] = {}
        last_price: dict[str, float] = {}
        equity_curve: list[tuple[object, float]] = []
        fills: list[SimulatedFill] = []

        for bar in merged_bars:
            last_price[bar.instrument] = bar.close
            context.positions = dict(positions)

            strategy.on_bar(bar)

            for order in context.drain_pending_orders():
                fill_price = bar.close
                signed_qty = order.quantity if order.transaction_type == "BUY" else -order.quantity
                cash -= signed_qty * fill_price
                positions[order.tradingsymbol] = positions.get(order.tradingsymbol, 0) + signed_qty
                fills.append(
                    SimulatedFill(
                        bar_timestamp=bar.timestamp,
                        instrument=order.tradingsymbol,
                        transaction_type=order.transaction_type,
                        quantity=order.quantity,
                        price=fill_price,
                    )
                )

            mark_to_market = sum(
                qty * last_price.get(instrument, 0.0) for instrument, qty in positions.items()
            )
            equity_curve.append((bar.timestamp, cash + mark_to_market))

        strategy.on_stop()

        return BacktestRunResult(
            equity_curve=equity_curve, fills=fills, final_positions=positions
        )
