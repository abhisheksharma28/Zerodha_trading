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

WEIGHTINGS = ("equal", "inverse_vol", "momentum_weighted", "score_weighted")
RULE_TYPES = ("none", "momentum_top_k", "composite_score")
FREQUENCIES = ("weekly", "monthly", "quarterly")

# factors the composite_score rule can blend. The price factors are
# computed causally from price / volume bars (available in a backtest);
# the fundamental factors come from present-day fundamentals (yfinance),
# carry look-ahead bias in a historical backtest, and are only applied on
# the live / paper signal.
_PRICE_FACTORS = frozenset({"momentum", "low_vol", "trend", "rs", "volume"})
_FUNDAMENTAL_FACTORS = ("value", "quality", "growth")
COMPOSITE_FACTORS = (*sorted(_PRICE_FACTORS), *_FUNDAMENTAL_FACTORS)


class SpecError(ValueError):
    """A basket spec that cannot be used as written."""


@dataclass(frozen=True)
class RuleSpec:
    type: str = "none"
    lookback: int = 126
    top_k: int = 5
    trend_ma: int = 200
    min_roc_pct: float = 0.0
    # anti-churn hysteresis: a currently-held name stays until its rank
    # slips past hold_k (>= top_k). 0 => hold_k == top_k (no buffer).
    hold_k: int = 0
    # a held name is also dropped if its lookback ROC falls below this
    # (entry uses min_roc_pct; this is the wider exit gate). None => off.
    exit_roc_pct: float | None = None
    # composite_score only: {factor: weight}, normalised. Empty => equal
    # weight across momentum/low_vol/trend.
    factor_weights: dict[str, float] = field(default_factory=dict)
    # composite_score only: a new candidate must beat the score of the held
    # name it would displace by this fraction before the swap is made
    # (0.10 = "10% better"). 0 => rank-only hysteresis. Damps churn from
    # names shuffling near the cutoff.
    replace_margin_pct: float = 0.0

    @property
    def active(self) -> bool:
        return self.type != "none"

    @property
    def effective_hold_k(self) -> int:
        return max(self.hold_k, self.top_k)

    @property
    def uses_fundamentals(self) -> bool:
        return any(
            self.factor_weights.get(f, 0.0) > 0 for f in COMPOSITE_FACTORS
            if f not in _PRICE_FACTORS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "lookback": self.lookback,
            "top_k": self.top_k,
            "trend_ma": self.trend_ma,
            "min_roc_pct": self.min_roc_pct,
            "hold_k": self.hold_k,
            "exit_roc_pct": self.exit_roc_pct,
            "factor_weights": dict(self.factor_weights),
            "replace_margin_pct": self.replace_margin_pct,
        }


@dataclass(frozen=True)
class SleeveSpec:
    id: str
    name: str
    weight_pct: float
    members: tuple[str, ...]
    weighting: str = "equal"
    rule: RuleSpec = field(default_factory=RuleSpec)
    # cap on any single member's weight as a fraction of the WHOLE basket
    # (0 => no cap). Applied after the weighting scheme; excess is
    # redistributed to the other selected names in the sleeve.
    max_weight_pct: float = 0.0
    # treat this sleeve as growth/equity risk for the regime gate. Cash /
    # gold / bond sleeves set this False so they are not de-risked.
    risk_asset: bool = True

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
            "max_weight_pct": self.max_weight_pct,
            "risk_asset": self.risk_asset,
        }


@dataclass(frozen=True)
class RegimeGate:
    benchmark: str = "NIFTY 50"
    ma: int = 200
    risk_off_scale: float = 0.5  # floor for risk-asset sleeves in a weak regime
    # hard_cut: any non-bull regime drops straight to risk_off_scale (no
    # graduated neutral/caution bands). For high-beta baskets (midcaps)
    # where staying partly invested through pullbacks costs too much.
    hard_cut: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark, "ma": self.ma,
            "risk_off_scale": self.risk_off_scale, "hard_cut": self.hard_cut,
        }


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.0   # global single-name cap, fraction of basket (0 => off)
    max_sector_pct: float = 0.0     # cap per sector bucket (0 => off)
    max_pair_corr: float = 0.0      # de-concentrate holdings whose return corr exceeds this (0 => off)
    corr_lookback: int = 126        # trading days of daily returns for the correlation estimate
    regime: RegimeGate | None = None

    @property
    def active(self) -> bool:
        return (
            self.max_position_pct > 0
            or self.max_sector_pct > 0
            or self.max_pair_corr > 0
            or self.regime is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_position_pct": self.max_position_pct,
            "max_sector_pct": self.max_sector_pct,
            "max_pair_corr": self.max_pair_corr,
            "corr_lookback": self.corr_lookback,
            "regime": self.regime.to_dict() if self.regime else None,
        }


@dataclass(frozen=True)
class BasketSpec:
    sleeves: tuple[SleeveSpec, ...]
    risk: RiskLimits = field(default_factory=RiskLimits)

    @property
    def symbols(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.sleeves:
            for m in s.members:
                seen.setdefault(m, None)
        if self.risk.regime:
            seen.setdefault(self.risk.regime.benchmark, None)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sleeves": [s.to_dict() for s in self.sleeves],
            "risk": self.risk.to_dict(),
        }


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
    hold_k = _int("hold_k", 0, 0, max(1, n_members))
    if hold_k and hold_k < top_k:
        raise SpecError(f"sleeve '{sleeve_id}': rule.hold_k ({hold_k}) must be >= top_k ({top_k})")
    try:
        min_roc = float(raw.get("min_roc_pct", 0.0))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sleeve_id}': rule.min_roc_pct must be a number") from exc
    exit_roc_raw = raw.get("exit_roc_pct")
    try:
        exit_roc = None if exit_roc_raw is None else float(exit_roc_raw)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sleeve_id}': rule.exit_roc_pct must be a number") from exc

    fw_raw = raw.get("factor_weights") or {}
    if not isinstance(fw_raw, dict):
        raise SpecError(f"sleeve '{sleeve_id}': rule.factor_weights must be an object")
    factor_weights: dict[str, float] = {}
    for k, v in fw_raw.items():
        if k not in COMPOSITE_FACTORS:
            raise SpecError(
                f"sleeve '{sleeve_id}': unknown factor '{k}' (use {COMPOSITE_FACTORS})"
            )
        try:
            fv = float(v)
        except (TypeError, ValueError) as exc:
            raise SpecError(f"sleeve '{sleeve_id}': factor_weights.{k} must be a number") from exc
        if fv < 0:
            raise SpecError(f"sleeve '{sleeve_id}': factor_weights.{k} must be >= 0")
        if fv > 0:
            factor_weights[k] = fv
    if rtype == "composite_score" and not factor_weights:
        factor_weights = {"momentum": 0.6, "trend": 0.2, "low_vol": 0.2}

    try:
        replace_margin = float(raw.get("replace_margin_pct", 0.0) or 0.0)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sleeve_id}': rule.replace_margin_pct must be a number") from exc
    if not 0.0 <= replace_margin <= 1.0:
        raise SpecError(f"sleeve '{sleeve_id}': rule.replace_margin_pct must be in [0, 1]")

    return RuleSpec(
        type=rtype, lookback=lookback, top_k=top_k, trend_ma=trend_ma, min_roc_pct=min_roc,
        hold_k=hold_k, exit_roc_pct=exit_roc, factor_weights=factor_weights,
        replace_margin_pct=replace_margin,
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

    try:
        max_weight_pct = float(raw.get("max_weight_pct", 0.0) or 0.0)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"sleeve '{sid}': max_weight_pct must be a number") from exc
    if not 0.0 <= max_weight_pct <= 100.0:
        raise SpecError(f"sleeve '{sid}': max_weight_pct must be in [0, 100]")
    risk_asset = bool(raw.get("risk_asset", True))

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
        weighting=weighting, rule=rule, max_weight_pct=max_weight_pct, risk_asset=risk_asset,
    )


def _parse_risk(raw: Any) -> RiskLimits:
    if raw is None:
        return RiskLimits()
    if not isinstance(raw, dict):
        raise SpecError("spec.risk must be an object")

    def _pct(key: str) -> float:
        try:
            v = float(raw.get(key, 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise SpecError(f"spec.risk.{key} must be a number") from exc
        if not 0.0 <= v <= 100.0:
            raise SpecError(f"spec.risk.{key} must be in [0, 100]")
        return v

    regime = None
    rg = raw.get("regime")
    if rg is not None:
        if not isinstance(rg, dict):
            raise SpecError("spec.risk.regime must be an object")
        try:
            ma = int(rg.get("ma", 200))
            scale = float(rg.get("risk_off_scale", 0.5))
        except (TypeError, ValueError) as exc:
            raise SpecError("spec.risk.regime ma / risk_off_scale must be numbers") from exc
        if not 20 <= ma <= 400:
            raise SpecError("spec.risk.regime.ma must be in [20, 400]")
        if not 0.0 <= scale <= 1.0:
            raise SpecError("spec.risk.regime.risk_off_scale must be in [0, 1]")
        regime = RegimeGate(
            benchmark=str(rg.get("benchmark") or "NIFTY 50"), ma=ma, risk_off_scale=scale,
            hard_cut=bool(rg.get("hard_cut", False)),
        )
    try:
        pair_corr = float(raw.get("max_pair_corr", 0.0) or 0.0)
        corr_lb = int(raw.get("corr_lookback", 126) or 126)
    except (TypeError, ValueError) as exc:
        raise SpecError("spec.risk.max_pair_corr / corr_lookback must be numbers") from exc
    if not 0.0 <= pair_corr <= 1.0:
        raise SpecError("spec.risk.max_pair_corr must be in [0, 1]")
    if not 20 <= corr_lb <= 504:
        raise SpecError("spec.risk.corr_lookback must be in [20, 504]")

    return RiskLimits(
        max_position_pct=_pct("max_position_pct"),
        max_sector_pct=_pct("max_sector_pct"),
        max_pair_corr=pair_corr,
        corr_lookback=corr_lb,
        regime=regime,
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

    risk = _parse_risk(raw.get("risk"))
    return BasketSpec(sleeves=tuple(sleeves), risk=risk)
