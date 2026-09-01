"""Mean Reversion — statistical reversion to a rolling mean.

Trades the Z-score of price against its own rolling mean/standard deviation,
with optional RSI, Bollinger and (intraday) VWAP confirmation filters, an
optional market-regime guard that switches off long entries when the
benchmark is in a strong downtrend, a Z-score stop, and a maximum holding
period.

Not guaranteed profitable. Mean reversion can lose heavily during
persistent trends — a cheap stock can always get cheaper. Validate
out-of-sample and keep the regime guard in mind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from app.strategies.base import Bar
from app.strategies.indicators import bollinger, rolling_volatility, rsi, zscore
from app.strategies.library.base import ParamSpec, TemplateMetadata, TemplateStrategy, preset


@dataclass
class _OpenPos:
    side: str
    entry_price: float
    entry_index: int


class MeanReversionStrategy(TemplateStrategy):
    SLUG: ClassVar[str] = "mean-reversion"
    NAME: ClassVar[str] = "Mean Reversion"
    CATEGORY: ClassVar[str] = "Mean Reversion"
    MIN_INSTRUMENTS: ClassVar[int] = 1

    PARAMS: ClassVar[dict[str, ParamSpec]] = {
        "lookback": ParamSpec("integer", 20, "Rolling window for mean / std / Z-score.",
                              min=3, max=500),
        "entry_zscore": ParamSpec("number", 2.0, "Absolute Z-score to enter.", min=0.1, max=10.0),
        "exit_zscore": ParamSpec("number", 0.0, "Z-score (toward 0) at which to exit.",
                                 min=0.0, max=10.0),
        "stop_zscore": ParamSpec("number", 3.5, "Z-score beyond entry that force-exits (0 off).",
                                 min=0.0, max=20.0, group="risk"),
        "allow_short": ParamSpec("boolean", False, "Permit short (Z >= +entry) entries."),
        "use_rsi_filter": ParamSpec("boolean", False, "Require RSI confirmation.", group="filter"),
        "rsi_period": ParamSpec("integer", 14, "RSI lookback.", min=2, max=100, group="filter"),
        "rsi_oversold": ParamSpec("number", 30.0, "Long requires RSI below this.",
                                  min=1.0, max=99.0, group="filter"),
        "rsi_overbought": ParamSpec("number", 70.0, "Short requires RSI above this.",
                                    min=1.0, max=99.0, group="filter"),
        "use_bollinger_filter": ParamSpec("boolean", False,
                                          "Long requires close below the lower Bollinger band.",
                                          group="filter"),
        "bollinger_std": ParamSpec("number", 2.0, "Bollinger band width in std devs.",
                                   min=0.5, max=5.0, group="filter"),
        "use_vwap_filter": ParamSpec("boolean", False,
                                     "Intraday: long requires close below session VWAP.",
                                     group="filter"),
        "min_volume": ParamSpec("number", 0.0, "Skip bars with volume below this.",
                                min=0.0, group="filter"),
        "max_volatility_pct": ParamSpec("number", 100.0,
                                        "Skip entries when per-bar realized vol (%) exceeds this.",
                                        min=0.0, max=1000.0, group="filter"),
        "max_holding_bars": ParamSpec("integer", 0, "Force exit after N bars (0 off).",
                                      min=0, max=100_000, group="risk"),
        "exchange": ParamSpec("string", "NSE", "Order exchange."),
        "product": ParamSpec("enum", "CNC", "Order product.", choices=("CNC", "MIS", "NRML")),
    }

    PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "conservative": preset(
            lookback=30, entry_zscore=2.5, exit_zscore=0.5, stop_zscore=4.0,
            use_rsi_filter=True, rsi_oversold=25.0, allow_short=False,
            regime_filter_enabled=True, sizing_method="fixed_capital",
            max_position_size_pct=10.0, max_holding_bars=15,
        ),
        "balanced": preset(
            lookback=20, entry_zscore=2.0, exit_zscore=0.0, stop_zscore=3.5,
            allow_short=False, regime_filter_enabled=True,
            sizing_method="fixed_quantity", fixed_quantity=1, max_holding_bars=20,
        ),
        "aggressive": preset(
            lookback=15, entry_zscore=1.5, exit_zscore=0.0, stop_zscore=3.0,
            allow_short=True, regime_filter_enabled=False,
            sizing_method="risk_per_trade", risk_per_trade_pct=1.0, max_holding_bars=10,
        ),
    }

    METADATA: ClassVar[TemplateMetadata] = TemplateMetadata(
        slug=SLUG, name=NAME, category=CATEGORY,
        description=(
            "Fades stretched moves: buys when price is unusually far below its rolling mean and "
            "exits as it reverts, with optional RSI / Bollinger / VWAP confirmation and a "
            "market-regime guard."
        ),
        logic=(
            "Each bar compute Z = (close - rollingMean) / rollingStd over `lookback`. Enter long "
            "when Z <= -entry_zscore (and every enabled filter agrees, and the regime guard "
            "permits longs); enter short when Z >= +entry_zscore if allow_short. Exit when Z "
            "reverts to +/- exit_zscore, when Z runs past +/- stop_zscore against the position, or "
            "after max_holding_bars."
        ),
        timeframe="day / 15minute / 5minute",
        market_types=["NSE equities", "liquid ETFs", "index futures"],
        supports_long=True, supports_short=True, supports_intraday=True, supports_swing=True,
        supports_market_neutral=False,
        complexity="Medium", time_horizon="Swing / Intraday",
        risks=[
            "Severe losses when a name trends persistently against the position.",
            "Cluster risk: many names dislocate together in a market-wide selloff.",
            "Filter over-fitting — each added filter is another parameter to validate.",
        ],
        best_for="Range-bound, liquid instruments; pairs well with a regime filter.",
        warning="Mean reversion can experience severe losses during persistent trends.",
        required_data=["OHLCV bars, at least lookback + 1 bars per instrument",
                       "benchmark bars in the stream if the regime filter is enabled"],
        example=(
            "On daily bars with lookback=20, entry_zscore=2: a long is opened when the close is "
            "two standard deviations below the 20-day mean and closed when the Z-score returns to "
            "0. Mechanics only — not a performance claim."
        ),
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self._open: dict[str, _OpenPos] = {}
        self._seen: dict[str, int] = {}
        self._session_day: dict[str, Any] = {}
        self._session_px: dict[str, list[float]] = {}
        self._session_vol: dict[str, list[float]] = {}

    def on_bar(self, bar: Bar) -> None:
        buf = self.ingest(bar)
        sym = bar.instrument
        self._seen[sym] = self._seen.get(sym, 0) + 1
        idx = self._seen[sym]
        self._track_session_vwap(bar)

        n = int(self.p["lookback"])
        closes = list(buf.closes)
        if len(closes) < n + 1:
            return

        z = zscore(closes, n)
        if z is None:
            return
        price = closes[-1]
        pos = self._open.get(sym)

        if pos is not None:
            if self._should_exit(pos, z, idx):
                self.rebalance_to(sym, 0, exchange=self.p["exchange"], product=self.p["product"])
                self._open.pop(sym, None)
            return

        if (buf.volumes[-1] or 0.0) < float(self.p["min_volume"]):
            return
        vol = rolling_volatility(closes, min(20, n))
        if vol is not None and vol * 100.0 > float(self.p["max_volatility_pct"]):
            return

        if z <= -float(self.p["entry_zscore"]) and self._long_filters_ok(sym, buf, closes):
            if not self.long_entries_allowed():
                return
            self._enter(sym, "long", price, idx)
        elif self.p["allow_short"] and z >= float(self.p["entry_zscore"]) and self._short_filters_ok(
            buf, closes
        ):
            self._enter(sym, "short", price, idx)

    # --- helpers -----------------------------------------------------

    def _enter(self, sym: str, side: str, price: float, idx: int) -> None:
        n = int(self.p["lookback"])
        std = None
        closes = list(self._buffer(sym).closes)
        if len(closes) >= n:
            from app.strategies.indicators import rolling_std

            std = rolling_std(closes, n)
        stop_dist = (std or price * 0.02) * max(1.0, float(self.p["stop_zscore"]))
        qty = self.size_position(price, stop_distance=stop_dist, symbol=sym)
        if qty <= 0:
            return
        self.submit(sym, "BUY" if side == "long" else "SELL", qty,
                    exchange=self.p["exchange"], product=self.p["product"])
        self._open[sym] = _OpenPos(side=side, entry_price=price, entry_index=idx)

    def _should_exit(self, pos: _OpenPos, z: float, idx: int) -> bool:
        ex = float(self.p["exit_zscore"])
        stop = float(self.p["stop_zscore"])
        if pos.side == "long":
            if z >= ex:
                return True
            if stop and z <= -stop:
                return True
        else:
            if z <= -ex:
                return True
            if stop and z >= stop:
                return True
        max_hold = int(self.p["max_holding_bars"])
        return bool(max_hold and (idx - pos.entry_index) >= max_hold)

    def _long_filters_ok(self, sym: str, buf, closes: list[float]) -> bool:
        if self.p["use_rsi_filter"]:
            r = rsi(closes, int(self.p["rsi_period"]))
            if r is None or r >= float(self.p["rsi_oversold"]):
                return False
        if self.p["use_bollinger_filter"]:
            band = bollinger(closes, int(self.p["lookback"]), float(self.p["bollinger_std"]))
            if band is None or closes[-1] >= band[0]:
                return False
        if self.p["use_vwap_filter"]:
            vwap_val = self._session_vwap(sym)
            if vwap_val is None or closes[-1] >= vwap_val:
                return False
        return True

    def _short_filters_ok(self, buf, closes: list[float]) -> bool:
        if self.p["use_rsi_filter"]:
            r = rsi(closes, int(self.p["rsi_period"]))
            if r is None or r <= float(self.p["rsi_overbought"]):
                return False
        if self.p["use_bollinger_filter"]:
            band = bollinger(closes, int(self.p["lookback"]), float(self.p["bollinger_std"]))
            if band is None or closes[-1] <= band[2]:
                return False
        return True

    # --- intraday session VWAP -------------------------------------

    def _track_session_vwap(self, bar: Bar) -> None:
        sym = bar.instrument
        day = self.bar_dt(bar).date()
        if self._session_day.get(sym) != day:
            self._session_day[sym] = day
            self._session_px[sym] = []
            self._session_vol[sym] = []
        typical = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
        self._session_px[sym].append(typical)
        self._session_vol[sym].append(float(bar.volume or 0.0))

    def _session_vwap(self, sym: str) -> float | None:
        px = self._session_px.get(sym) or []
        vol = self._session_vol.get(sym) or []
        tv = sum(vol)
        if not px or tv <= 0:
            return None
        return sum(p * v for p, v in zip(px, vol, strict=True)) / tv
