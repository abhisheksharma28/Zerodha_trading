"""Option-chain view + strike-selection engine for one underlying+expiry.

The strategy needs three CALL strikes: ~otm_distance points OTM from spot
(A), then ~strike_spacing above that (B), then again above (C). The
exchange strike grid may not contain the exact theoretical strike, so
``select_strike`` snaps to the nearest *listed* strike and records the
theoretical value, the actual value, and the difference. Nothing is chosen
silently or assumed to exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.exceptions import ValidationError
from app.options.instruments_nfo import OptionContract, load_option_contracts


@dataclass(frozen=True)
class StrikeSelection:
    label: str            # "A" | "B" | "C"
    theoretical_strike: float
    actual_strike: float
    difference: float     # actual - theoretical
    contract: OptionContract


class CallChain:
    """CALL contracts for one underlying + expiry, indexed by strike."""

    def __init__(self, underlying: str, expiry: date, contracts: list[OptionContract]) -> None:
        self.underlying = underlying
        self.expiry = expiry
        self._by_strike: dict[float, OptionContract] = {
            c.strike: c for c in contracts
            if c.name == underlying and c.expiry == expiry and c.option_type == "CE"
        }
        if not self._by_strike:
            raise ValidationError(
                f"No CALL contracts listed for {underlying} expiry {expiry.isoformat()}."
            )
        self.strikes: list[float] = sorted(self._by_strike)

    @classmethod
    def load(cls, underlying: str, expiry: date) -> CallChain:
        return cls(underlying, expiry, load_option_contracts(underlying))

    @property
    def strike_step(self) -> float:
        """Modal gap between adjacent listed strikes."""
        gaps: dict[float, int] = {}
        for a, b in zip(self.strikes, self.strikes[1:], strict=False):
            g = round(b - a, 4)
            gaps[g] = gaps.get(g, 0) + 1
        return max(gaps, key=lambda k: gaps[k]) if gaps else 50.0

    def contract_at(self, strike: float) -> OptionContract | None:
        return self._by_strike.get(strike)

    def nearest_listed_strike(self, target: float) -> float:
        return min(self.strikes, key=lambda s: (abs(s - target), s))

    def select_strike(self, label: str, theoretical: float) -> StrikeSelection:
        actual = self.nearest_listed_strike(theoretical)
        return StrikeSelection(
            label=label,
            theoretical_strike=round(theoretical, 4),
            actual_strike=actual,
            difference=round(actual - theoretical, 4),
            contract=self._by_strike[actual],
        )


def select_ratio_strikes(
    chain: CallChain,
    spot: float,
    *,
    otm_distance: float = 300.0,
    strike_spacing: float = 300.0,
) -> list[StrikeSelection]:
    """A (spot + otm_distance), B (A + strike_spacing), C (B + strike_spacing).

    Snapped to listed strikes. Raises if fewer than three distinct listed
    strikes result (grid too coarse for the configured spacing)."""
    theo_a = spot + otm_distance
    sel_a = chain.select_strike("A", theo_a)
    sel_b = chain.select_strike("B", sel_a.actual_strike + strike_spacing)
    sel_c = chain.select_strike("C", sel_b.actual_strike + strike_spacing)

    strikes = [sel_a.actual_strike, sel_b.actual_strike, sel_c.actual_strike]
    if len({*strikes}) != 3 or strikes != sorted(strikes):
        raise ValidationError(
            "Strike grid too coarse for the configured spacing: resolved strikes "
            f"{strikes} are not three strictly increasing listed strikes."
        )
    return [sel_a, sel_b, sel_c]
