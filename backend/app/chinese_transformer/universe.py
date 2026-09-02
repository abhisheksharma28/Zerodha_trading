"""Point-in-time universe management for the Chinese Transformer.

``UniverseManager.members(as_of)`` is the single entry point every other
component uses to ask "which stocks were tradable on this date?". It applies
configurable eligibility filters (price, liquidity, history, missing-data)
so the ranker never scores a name it could not have held.

HONEST LIMITATION — survivorship bias
-------------------------------------
The backing membership list (``app.market_data.nse_universe``) is *today's*
index constituents. NSE does not expose historical point-in-time index
membership, delisting dates or IPO dates through the data this platform
has. So ``members(as_of)`` currently returns the same base list for every
date and the ``as_of`` argument only drives the *data-derived* filters
(a name with no history before ``as_of`` is dropped). Historical backtests
therefore over-represent survivors. This is disclosed on every result, the
way the existing library backtest reports already do it. The interface is
built to accept a real point-in-time membership table the moment one exists
— see ``_membership_asof``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.market_data.nse_universe import NIFTY_50, NIFTY_100, NIFTY_200

_SECTOR_BY_SYMBOL: dict[str, str] = {sym: sector for sym, _name, sector in NIFTY_50}

_UNIVERSES: dict[str, list[str]] = {
    "NIFTY_50": [s for s, _n, _sct in NIFTY_50],
    "NIFTY_100": list(NIFTY_100),
    "NIFTY_200": list(NIFTY_200),
}


@dataclass(frozen=True)
class UniverseConfig:
    name: str = "NIFTY_100"
    min_price: float = 20.0
    min_avg_daily_value: float = 5.0e7          # ₹5 cr median daily traded value
    min_history_bars: int = 252                  # ~1y of clean daily bars
    max_missing_pct: float = 5.0                 # reject a name missing >5% of bars
    exclude_symbols: tuple[str, ...] = ()

    def base_symbols(self) -> list[str]:
        try:
            syms = _UNIVERSES[self.name]
        except KeyError as exc:
            raise ValueError(
                f"Unknown universe '{self.name}' — {sorted(_UNIVERSES)}"
            ) from exc
        ex = set(self.exclude_symbols)
        return [s for s in syms if s not in ex]


@dataclass
class EligibilityResult:
    as_of: date
    eligible: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)   # symbol -> reason

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "eligible_count": len(self.eligible),
            "eligible": self.eligible,
            "dropped": self.dropped,
        }


class UniverseManager:
    def __init__(self, config: UniverseConfig | None = None) -> None:
        self.config = config or UniverseConfig()

    # --- membership -------------------------------------------------

    def _membership_asof(self, as_of: date) -> list[str]:  # noqa: ARG002
        """Point-in-time index membership. Placeholder: returns the current
        list for every date (see module docstring). Swap the body for a
        lookup against a real membership table when one lands."""
        return self.config.base_symbols()

    def sector(self, symbol: str) -> str:
        return _SECTOR_BY_SYMBOL.get(symbol, "Unknown")

    def sector_map(self, symbols: list[str]) -> dict[str, str]:
        return {s: self.sector(s) for s in symbols}

    # --- eligibility ----------------------------------------------

    def screen(
        self,
        as_of: date,
        *,
        bars_by_symbol: dict[str, list],
        expected_bars: int | None = None,
    ) -> EligibilityResult:
        """Apply data-derived eligibility filters as of ``as_of``.

        ``bars_by_symbol`` holds only bars dated on/before ``as_of`` (the
        caller slices causally). ``expected_bars`` is the count a fully
        populated name would have over the same window; used for the
        missing-data filter.
        """
        cfg = self.config
        res = EligibilityResult(as_of=as_of)
        for sym in self._membership_asof(as_of):
            bars = bars_by_symbol.get(sym) or []
            if len(bars) < cfg.min_history_bars:
                res.dropped[sym] = f"history {len(bars)} < {cfg.min_history_bars} bars"
                continue
            if expected_bars and expected_bars > 0:
                missing_pct = 100.0 * (1.0 - len(bars) / expected_bars)
                if missing_pct > cfg.max_missing_pct:
                    res.dropped[sym] = f"missing {missing_pct:.1f}% of bars"
                    continue
            last = bars[-1]
            close = float(getattr(last, "close", 0.0) or 0.0)
            if close < cfg.min_price:
                res.dropped[sym] = f"price {close:.2f} < {cfg.min_price}"
                continue
            recent = bars[-20:]
            if recent:
                adv = sum(
                    float(getattr(b, "close", 0.0) or 0.0)
                    * float(getattr(b, "volume", 0.0) or 0.0)
                    for b in recent
                ) / len(recent)
                if adv < cfg.min_avg_daily_value:
                    res.dropped[sym] = f"ADV ₹{adv:,.0f} < ₹{cfg.min_avg_daily_value:,.0f}"
                    continue
            res.eligible.append(sym)
        return res
