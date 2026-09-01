"""Shared framework for the strategy templates.

``TemplateStrategy`` extends the platform's ``BaseStrategy`` with the parts
every template needs and that must behave identically no matter which mode
(backtest / simulation / paper / live) the strategy runs in:

* a declarative parameter schema (type / default / min / max / description)
  that is validated on construction and is also what the frontend renders
  its parameter form from — nothing about the form is hard-coded in React;
* causal rolling buffers per instrument (a strategy only ever sees the
  current bar and earlier ones, which is what keeps the templates free of
  look-ahead bias);
* reusable position sizing (fixed qty / fixed capital / equal weight /
  volatility-adjusted / risk-per-trade);
* an optional, simple market-regime filter driven by a benchmark symbol.

The strategy expresses intent only through ``context.submit_order`` — it
never touches a broker, the database, or the clock directly.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from app.brokers.base import OrderRequest
from app.strategies.base import Bar, BaseStrategy, StrategyContext
from app.strategies.indicators import ema, roc, rolling_volatility, sma

IST = timezone(timedelta(hours=5, minutes=30))

# Kite bar-interval label -> approximate seconds, for buffer sizing only.
_INTERVAL_SECONDS = {
    "minute": 60,
    "3minute": 180,
    "5minute": 300,
    "10minute": 600,
    "15minute": 900,
    "30minute": 1800,
    "60minute": 3600,
    "day": 86400,
}


class ParamError(ValueError):
    """Raised when supplied parameters violate the template's schema."""


@dataclass(frozen=True)
class ParamSpec:
    type: str  # "integer" | "number" | "string" | "boolean" | "enum"
    default: Any
    description: str
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] | None = None
    group: str = "core"  # "core" | "filter" | "risk" | "sizing"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "group": self.group,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.choices is not None:
            d["choices"] = list(self.choices)
        return d

    def coerce(self, name: str, value: Any) -> Any:
        if value is None:
            return self.default
        try:
            if self.type == "integer":
                value = int(value)
            elif self.type == "number":
                value = float(value)
            elif self.type == "boolean":
                value = bool(value) if not isinstance(value, str) else value.lower() == "true"
            elif self.type in ("string", "enum"):
                value = str(value)
        except (TypeError, ValueError) as exc:
            raise ParamError(f"{name}: cannot be read as {self.type} ({value!r})") from exc

        if self.type in ("integer", "number"):
            if self.min is not None and value < self.min:
                raise ParamError(f"{name}: {value} < min {self.min}")
            if self.max is not None and value > self.max:
                raise ParamError(f"{name}: {value} > max {self.max}")
        if self.choices is not None and value not in self.choices:
            raise ParamError(f"{name}: {value!r} not in {list(self.choices)}")
        return value


# Parameters shared by every template. Individual templates extend this.
_COMMON_PARAMS: dict[str, ParamSpec] = {
    "capital_allocation": ParamSpec(
        "number", 1_000_000.0, "Notional capital this strategy sizes against (INR).",
        min=1000.0, group="sizing",
    ),
    "sizing_method": ParamSpec(
        "enum", "fixed_quantity",
        "How order quantity is chosen.",
        choices=("fixed_quantity", "fixed_capital", "equal_weight", "volatility_adjusted",
                 "risk_per_trade"),
        group="sizing",
    ),
    "fixed_quantity": ParamSpec(
        "integer", 1, "Quantity per order when sizing_method == fixed_quantity.",
        min=1, max=100_000, group="sizing",
    ),
    "risk_per_trade_pct": ParamSpec(
        "number", 1.0,
        "Percent of capital_allocation risked per trade when sizing_method == risk_per_trade.",
        min=0.01, max=100.0, group="sizing",
    ),
    "target_volatility_pct": ParamSpec(
        "number", 2.0,
        "Target per-bar volatility (%) for sizing_method == volatility_adjusted.",
        min=0.01, max=100.0, group="sizing",
    ),
    "max_position_size_pct": ParamSpec(
        "number", 20.0, "Cap on a single position as % of capital_allocation.",
        min=0.1, max=100.0, group="risk",
    ),
    "regime_filter_enabled": ParamSpec(
        "boolean", False,
        "Disable new long entries when the benchmark is in a downtrend / high-vol regime.",
        group="filter",
    ),
    "regime_benchmark": ParamSpec(
        "string", "NIFTY 50",
        "Benchmark tradingsymbol used by the regime filter (must be in the instrument stream).",
        group="filter",
    ),
    "regime_trend_lookback": ParamSpec(
        "integer", 50, "Benchmark SMA lookback for the regime trend check.",
        min=5, max=400, group="filter",
    ),
}


@dataclass
class InstrumentBuffer:
    bars: deque[Bar]
    closes: deque[float]
    highs: deque[float]
    lows: deque[float]
    volumes: deque[float]
    prev_close: float | None = None


@dataclass
class TemplateMetadata:
    slug: str
    name: str
    category: str
    description: str
    logic: str
    timeframe: str
    market_types: list[str]
    supports_long: bool
    supports_short: bool
    supports_intraday: bool
    supports_swing: bool
    supports_market_neutral: bool
    complexity: str  # "Low" | "Medium" | "High"
    time_horizon: str  # "Intraday" | "Swing" | "Positional" | "Market-neutral"
    risks: list[str]
    best_for: str
    warning: str
    required_data: list[str]
    example: str

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__}


class TemplateStrategy(BaseStrategy):
    # --- required class-level declarations on each concrete template -------
    SLUG: ClassVar[str] = ""
    NAME: ClassVar[str] = ""
    CATEGORY: ClassVar[str] = ""
    PARAMS: ClassVar[dict[str, ParamSpec]] = {}
    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {}
    METADATA: ClassVar[TemplateMetadata]
    MIN_INSTRUMENTS: ClassVar[int] = 1
    MAX_INSTRUMENTS: ClassVar[int | None] = None

    # --- construction -----------------------------------------------------

    def __init__(self, context: StrategyContext) -> None:
        super().__init__(context)
        self.p: dict[str, Any] = self.resolve_params(context.parameters or {})
        self._buffers: dict[str, InstrumentBuffer] = {}
        self._buf_maxlen = self._compute_buffer_maxlen()

    @classmethod
    def all_params(cls) -> dict[str, ParamSpec]:
        merged = dict(_COMMON_PARAMS)
        merged.update(cls.PARAMS)
        return merged

    @classmethod
    def resolve_params(cls, supplied: dict[str, Any]) -> dict[str, Any]:
        schema = cls.all_params()
        unknown = set(supplied) - set(schema)
        if unknown:
            raise ParamError(f"Unknown parameter(s): {sorted(unknown)}")
        return {name: spec.coerce(name, supplied.get(name)) for name, spec in schema.items()}

    @classmethod
    def parameter_schema(cls) -> dict[str, Any]:
        return {name: spec.to_dict() for name, spec in cls.all_params().items()}

    @classmethod
    def presets(cls) -> dict[str, dict[str, Any]]:
        """Research presets — starting points, not recommendations."""
        return cls.PRESETS

    def _compute_buffer_maxlen(self) -> int:
        candidates = [
            int(v)
            for k, v in self.p.items()
            if ("lookback" in k or "period" in k or "window" in k or "regression" in k)
            and isinstance(v, (int, float))
        ]
        return max(candidates + [200]) + 50

    # --- bar plumbing ----------------------------------------------------

    def _buffer(self, symbol: str) -> InstrumentBuffer:
        buf = self._buffers.get(symbol)
        if buf is None:
            m = self._buf_maxlen
            buf = InstrumentBuffer(
                bars=deque(maxlen=m),
                closes=deque(maxlen=m),
                highs=deque(maxlen=m),
                lows=deque(maxlen=m),
                volumes=deque(maxlen=m),
            )
            self._buffers[symbol] = buf
        return buf

    def ingest(self, bar: Bar) -> InstrumentBuffer:
        """Append a bar to its instrument buffer. Call once at the top of
        ``on_bar`` before making any decision."""
        buf = self._buffer(bar.instrument)
        if buf.bars:
            buf.prev_close = buf.bars[-1].close
        buf.bars.append(bar)
        buf.closes.append(float(bar.close))
        buf.highs.append(float(bar.high))
        buf.lows.append(float(bar.low))
        buf.volumes.append(float(bar.volume or 0.0))
        return buf

    @staticmethod
    def bar_dt(bar: Bar) -> datetime:
        """Bar timestamp as a timezone-aware datetime in Asia/Kolkata."""
        ts = bar.timestamp
        if isinstance(ts, datetime):
            dt = ts
        else:
            s = str(ts).strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                # Kite sometimes uses "+0530" with no colon.
                if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
                    s = s[:-2] + ":" + s[-2:]
                dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)

    # --- positions / orders --------------------------------------------

    def position(self, symbol: str) -> int:
        return int(self.context.positions.get(symbol, 0))

    def submit(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        exchange: str = "NSE",
        product: str = "MIS",
        order_type: str = "MARKET",
        price: float | None = None,
    ) -> None:
        if quantity <= 0:
            return
        self.context.submit_order(
            OrderRequest(
                tradingsymbol=symbol,
                exchange=exchange,
                transaction_type="BUY" if side.upper() == "BUY" else "SELL",
                order_type=order_type,
                quantity=int(quantity),
                product=product,
                price=price,
                market_protection=0.05 if order_type in ("MARKET", "SL-M") else None,
            )
        )

    def rebalance_to(
        self, symbol: str, target_qty: int, *, exchange: str = "NSE", product: str = "MIS"
    ) -> None:
        """Emit the single order that moves the current position to
        ``target_qty`` (no-op if already there)."""
        delta = int(target_qty) - self.position(symbol)
        if delta > 0:
            self.submit(symbol, "BUY", delta, exchange=exchange, product=product)
        elif delta < 0:
            self.submit(symbol, "SELL", -delta, exchange=exchange, product=product)

    # --- position sizing ---------------------------------------------

    def size_position(self, price: float, *, stop_distance: float | None = None,
                      symbol: str | None = None) -> int:
        method = self.p["sizing_method"]
        capital = float(self.p["capital_allocation"])
        cap_qty_ceiling = self._max_position_qty(price, capital)

        if method == "fixed_quantity" or price <= 0:
            qty = int(self.p["fixed_quantity"])
        elif method == "fixed_capital":
            qty = int(capital // price)
        elif method == "equal_weight":
            n = max(1, len(self._buffers) or 1)
            qty = int((capital / n) // price)
        elif method == "volatility_adjusted":
            qty = self._vol_adjusted_qty(price, capital, symbol)
        elif method == "risk_per_trade":
            if not stop_distance or stop_distance <= 0:
                qty = int(self.p["fixed_quantity"])
            else:
                risk_capital = capital * float(self.p["risk_per_trade_pct"]) / 100.0
                qty = int(risk_capital // stop_distance)
        else:  # pragma: no cover - schema prevents this
            qty = int(self.p["fixed_quantity"])

        return max(0, min(qty, cap_qty_ceiling))

    def _max_position_qty(self, price: float, capital: float) -> int:
        if price <= 0:
            return 0
        cap_value = capital * float(self.p["max_position_size_pct"]) / 100.0
        return max(1, int(cap_value // price))

    def _vol_adjusted_qty(self, price: float, capital: float, symbol: str | None) -> int:
        base = int((capital * float(self.p["max_position_size_pct"]) / 100.0) // price) if price else 0
        if not symbol or symbol not in self._buffers:
            return base
        realized = rolling_volatility(list(self._buffers[symbol].closes), 20)
        target = float(self.p["target_volatility_pct"]) / 100.0
        if not realized or realized <= 0:
            return base
        scale = min(1.0, target / realized)
        return max(0, int(base * scale))

    # --- market-regime filter ------------------------------------------

    def long_entries_allowed(self) -> bool:
        """False when the regime filter is on and the benchmark is below its
        trend SMA. Fails open (returns True) if the benchmark isn't in the
        stream yet, so a mis-set benchmark never silently blocks everything
        forever — it just doesn't filter."""
        if not self.p["regime_filter_enabled"]:
            return True
        bench = self.p["regime_benchmark"]
        buf = self._buffers.get(bench)
        if buf is None or len(buf.closes) < int(self.p["regime_trend_lookback"]):
            return True
        trend = sma(list(buf.closes), int(self.p["regime_trend_lookback"]))
        return trend is not None and buf.closes[-1] >= trend

    # --- small helpers -------------------------------------------------

    @staticmethod
    def _ma(values: Sequence[float], period: int, kind: str) -> float | None:
        return ema(values, period) if kind.lower() == "ema" else sma(values, period)

    @staticmethod
    def _roc(values: Sequence[float], period: int) -> float | None:
        return roc(values, period)

    def interval_seconds(self, deployment_timeframe: str | None = None) -> int:
        return _INTERVAL_SECONDS.get(deployment_timeframe or "day", 86400)

    # default no-op hooks so a template only overrides what it needs
    def on_start(self) -> None:  # noqa: D401
        pass

    def on_stop(self) -> None:
        pass


def preset(**params: Any) -> dict[str, Any]:
    """Tiny helper to keep PRESETS dict literals readable."""
    return dict(params)


def merge_metadata_defaults(md: TemplateMetadata, cls: type[TemplateStrategy]) -> dict[str, Any]:
    out = md.to_dict()
    out["parameters"] = cls.parameter_schema()
    out["presets"] = cls.presets()
    out["min_instruments"] = cls.MIN_INSTRUMENTS
    out["max_instruments"] = cls.MAX_INSTRUMENTS
    return out
