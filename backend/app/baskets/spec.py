"""Parse + validate a basket spec (the ``spec`` JSONB on the Basket row).

Shape::

    {
      "sleeves": [
        {
          "id": "equity-core",
          "name": "Equity core",
          "weight_pct": 60.0,
          "weighting": "inverse_vol",          # equal | inverse_vol | momentum_weighted
          "members": ["RELIANCE", "HDFCBANK", ...],
          "rule": {
            "type": "momentum_top_k",          # none | momentum_top_k
            "lookback": 126,
            "top_k": 8,
            "trend_ma": 200,                    # 0 disables the trend filter
            "min_roc_pct": 0.0
          }
        },
        { "id": "gold", "name": "Gold ballast", "weight_pct": 25.0,
          "weighting": "equal", "members": ["GOLDBEES"], "rule": {"type": "none"} }
      ]
    }

Sleeve weights must sum to 100 (± 0.5). Every member is an NSE trading
symbol; the exchange is implicit (NSE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WEIGHTINGS = ("equal", "inverse_vol", "momentum_weighted")
RULE_TYPES = ("none", "momentum_top_k")
FREQUENCIES = ("weekly", "monthly", "quarterly")


class SpecError(ValueError):
    """A basket spec that cannot be used as written."""


@dataclass(frozen=True)
class RuleSpec:
    type: str = "none"
    lookback: int = 126
    top_k: int = 5
    trend_ma: int = 200
    min_roc_pct: float = 0.0

    @property
    def active(self) -> bool:
        return self.type != "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "lookback": self.lookback,
            "top_k": self.top_k,
            "trend_ma": self.trend_ma,
            "min_roc_pct": self.min_roc_pct,
        }


@dataclass(frozen=True)
class SleeveSpec:
    id: str
    name: str
    weight_pct: float
    members: tuple[str, ...]
    weighting: str = "equal"
    rule: RuleSpec = field(default_factory=RuleSpec)

    @property
    def weight(self) -> float:
        return self.weight_pct / 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "weight_pct": self.weight_pct,
            "weighting": self.weighting,
            "members": list(self.members),
            "rule": self.rule.to_dict(),
        }


@dataclass(frozen=True)
class BasketSpec:
    sleeves: tuple[SleeveSpec, ...]

    @property
    def symbols(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.sleeves:
            for m in s.members:
                seen.setdefault(m, None)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        return {"sleeves": [s.to_dict() for s in self.sleeves]}


def _clean_symbol(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SpecError(f"member symbol must be a non-empty string, got {raw!r}")
    sym = raw.strip().upper()
    if ":" in sym:  # accept "NSE:GOLDBEES" and drop the exchange
        sym = sym.split(":", 1)[1]
    return sym


def _parse_rule(raw: Any, *, sleeve_id: str, n_members: int) -> RuleSpec:
    if raw is None:
        return RuleSpec()
    if not isinstance(raw, dict):
        raise SpecError(f"sleeve '{sleeve_id}': rule must be an object")
    rtype = str(raw.get("type", "none")).strip() or "none"
    if rtype not in RULE_TYPES:
        raise SpecError(
            f"sleeve '{sleeve_id}': rule.type must be one of {RULE_TYPES}, got {rtype!r}"
        )
    if rtype == "none":
        return RuleSpec()

    def _int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            v = int(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise SpecError(f"sleeve '{sleeve_id}': rule.{key} must be an integer") from exc
        if not lo <= v <= hi:
            raise SpecError(f"sleeve '{sleeve_id}': rule.{key} must be in [{lo}, {hi}]")
        return v

    lookback = _int("lookback", 126, 5, 750)
    top_k = _int("top_k", min(5, n_members), 1, max(1, n_members))
    trend_ma = _int("trend_ma", 200, 0, 400)
    try:
        min_roc = float(raw.get("min_roc_pct", 0.0))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sleeve_id}': rule.min_roc_pct must be a number") from exc
    return RuleSpec(
        type=rtype, lookback=lookback, top_k=top_k, trend_ma=trend_ma, min_roc_pct=min_roc
    )


def _parse_sleeve(raw: Any, *, idx: int) -> SleeveSpec:
    if not isinstance(raw, dict):
        raise SpecError(f"sleeve #{idx + 1} must be an object")
    sid = str(raw.get("id") or raw.get("name") or f"sleeve-{idx + 1}").strip()
    name = str(raw.get("name") or sid).strip()

    try:
        weight_pct = float(raw.get("weight_pct"))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sid}': weight_pct must be a number") from exc
    if not 0 < weight_pct <= 100:
        raise SpecError(f"sleeve '{sid}': weight_pct must be in (0, 100], got {weight_pct}")

    weighting = str(raw.get("weighting", "equal")).strip() or "equal"
    if weighting not in WEIGHTINGS:
        raise SpecError(
            f"sleeve '{sid}': weighting must be one of {WEIGHTINGS}, got {weighting!r}"
        )

    members_raw = raw.get("members") or []
    if not isinstance(members_raw, (list, tuple)) or not members_raw:
        raise SpecError(f"sleeve '{sid}': needs a non-empty members list")
    members: list[str] = []
    for m in members_raw:
        sym = _clean_symbol(m)
        if sym not in members:
            members.append(sym)

    rule = _parse_rule(raw.get("rule"), sleeve_id=sid, n_members=len(members))
    if rule.active and rule.top_k > len(members):
        raise SpecError(
            f"sleeve '{sid}': rule.top_k ({rule.top_k}) exceeds member count ({len(members)})"
        )
    return SleeveSpec(
        id=sid, name=name, weight_pct=weight_pct, members=tuple(members),
        weighting=weighting, rule=rule,
    )


def parse_spec(raw: Any) -> BasketSpec:
    """Validate ``raw`` (a dict) into a :class:`BasketSpec` or raise
    :class:`SpecError`."""
    if not isinstance(raw, dict):
        raise SpecError("spec must be an object with a 'sleeves' list")
    sleeves_raw = raw.get("sleeves")
    if not isinstance(sleeves_raw, (list, tuple)) or not sleeves_raw:
        raise SpecError("spec.sleeves must be a non-empty list")
    if len(sleeves_raw) > 12:
        raise SpecError("a basket may have at most 12 sleeves")

    sleeves = [_parse_sleeve(s, idx=i) for i, s in enumerate(sleeves_raw)]

    ids = [s.id for s in sleeves]
    if len(set(ids)) != len(ids):
        raise SpecError("sleeve ids must be unique")

    total = sum(s.weight_pct for s in sleeves)
    if abs(total - 100.0) > 0.5:
        raise SpecError(f"sleeve weights must sum to 100, got {total:.2f}")

    return BasketSpec(sleeves=tuple(sleeves))
