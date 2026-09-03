"""Rebalance engine for a basket.

Two pure functions, no DB / broker:

  ``resolve_targets(spec, bars_by_symbol, as_of)``
      -> the target weight per symbol for a rebalance dated ``as_of``.
      Causal: only bars at or before ``as_of`` are looked at.

  ``plan_orders(targets, holdings, prices, portfolio_value, drift_band_pct)``
      -> the BUY/SELL diff needed to move current holdings to ``targets``,
      skipping sleeves that have not drifted past the band (but always
      exiting names that dropped out of the target).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.baskets.spec import BasketSpec, SleeveSpec


def _as_dt(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    if isinstance(ts, date):
        return datetime(ts.year, ts.month, ts.day)
    s = str(ts)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.fromisoformat(s[:19]).replace(tzinfo=None)


def _closes_upto(bars: list[Any], as_of: datetime) -> list[float]:
    out: list[float] = []
    for b in bars:
        if _as_dt(b.timestamp) <= as_of:
            out.append(float(b.close))
    return out


def _roc_pct(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback:
        return None
    past = closes[-lookback - 1]
    if past <= 0:
        return None
    return (closes[-1] / past - 1.0) * 100.0


def _sma(closes: list[float], window: int) -> float | None:
    if window <= 0 or len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _daily_vol(closes: list[float], window: int) -> float | None:
    seg = closes[-(window + 1):]
    if len(seg) < 5:
        return None
    rets = [seg[i] / seg[i - 1] - 1.0 for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) < 4:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


@dataclass
class SleeveResolution:
    sleeve_id: str
    name: str
    target_pct: float
    selected: dict[str, float]  # symbol -> weight (fraction of the whole basket)
    cash_pct: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class ResolveResult:
    weights: dict[str, float]           # symbol -> fraction of the basket (sum <= 1)
    cash_weight: float
    per_sleeve: list[SleeveResolution]
    notes: list[str] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return sum(self.weights.values())


def _rank_members(
    sleeve: SleeveSpec, bars_by_symbol: dict[str, list[Any]], as_of: datetime
) -> tuple[list[str], list[str]]:
    """Apply the sleeve rule -> (selected symbols, notes)."""
    notes: list[str] = []
    rule = sleeve.rule
    have = [m for m in sleeve.members if bars_by_symbol.get(m)]
    missing = [m for m in sleeve.members if not bars_by_symbol.get(m)]
    if missing:
        notes.append(f"no price history for {', '.join(missing)}")

    if not rule.active:
        return have, notes

    scored: list[tuple[str, float]] = []
    for m in have:
        closes = _closes_upto(bars_by_symbol[m], as_of)
        roc = _roc_pct(closes, rule.lookback)
        if roc is None:
            notes.append(f"{m}: <{rule.lookback} bars, skipped")
            continue
        if roc < rule.min_roc_pct:
            continue
        if rule.trend_ma > 0:
            ma = _sma(closes, rule.trend_ma)
            if ma is None or closes[-1] < ma:
                continue
        scored.append((m, roc))

    scored.sort(key=lambda t: t[1], reverse=True)
    selected = [m for m, _ in scored[: rule.top_k]]
    if not selected:
        notes.append("rule cleared no members — sleeve goes to cash")
    return selected, notes


def _weight_within_sleeve(
    sleeve: SleeveSpec, selected: list[str],
    bars_by_symbol: dict[str, list[Any]], as_of: datetime,
) -> dict[str, float]:
    """Fractions within the sleeve (sum to 1) per the weighting scheme."""
    n = len(selected)
    if n == 0:
        return {}
    if sleeve.weighting == "equal":
        return dict.fromkeys(selected, 1.0 / n)

    if sleeve.weighting == "inverse_vol":
        window = min(sleeve.rule.lookback, 90) if sleeve.rule.active else 90
        inv: dict[str, float] = {}
        for m in selected:
            vol = _daily_vol(_closes_upto(bars_by_symbol[m], as_of), window)
            inv[m] = 1.0 / vol if vol and vol > 1e-9 else 0.0
        tot = sum(inv.values())
        if tot <= 0:
            return dict.fromkeys(selected, 1.0 / n)
        return {m: v / tot for m, v in inv.items()}

    if sleeve.weighting == "momentum_weighted":
        lb = sleeve.rule.lookback if sleeve.rule.active else 126
        raw: dict[str, float] = {}
        for m in selected:
            roc = _roc_pct(_closes_upto(bars_by_symbol[m], as_of), lb) or 0.0
            raw[m] = max(roc, 0.0)
        tot = sum(raw.values())
        if tot <= 0:
            return dict.fromkeys(selected, 1.0 / n)
        return {m: v / tot for m, v in raw.items()}

    return dict.fromkeys(selected, 1.0 / n)


def resolve_targets(
    spec: BasketSpec, bars_by_symbol: dict[str, list[Any]], as_of: datetime | str
) -> ResolveResult:
    as_of_dt = _as_dt(as_of)
    weights: dict[str, float] = {}
    per_sleeve: list[SleeveResolution] = []
    notes: list[str] = []

    for sleeve in spec.sleeves:
        selected, s_notes = _rank_members(sleeve, bars_by_symbol, as_of_dt)
        within = _weight_within_sleeve(sleeve, selected, bars_by_symbol, as_of_dt)
        sleeve_weights = {m: frac * sleeve.weight for m, frac in within.items()}
        for m, w in sleeve_weights.items():
            weights[m] = weights.get(m, 0.0) + w
        filled = sum(sleeve_weights.values())
        cash_pct = max(sleeve.weight_pct - filled * 100.0, 0.0)
        res = SleeveResolution(
            sleeve_id=sleeve.id, name=sleeve.name, target_pct=sleeve.weight_pct,
            selected=sleeve_weights, cash_pct=cash_pct, notes=s_notes,
        )
        per_sleeve.append(res)
        notes.extend(f"{sleeve.id}: {n}" for n in s_notes)

    invested = sum(weights.values())
    return ResolveResult(
        weights=weights, cash_weight=max(1.0 - invested, 0.0),
        per_sleeve=per_sleeve, notes=notes,
    )


@dataclass
class OrderIntent:
    symbol: str
    side: str          # BUY | SELL
    qty: int
    est_value: float
    from_weight: float
    to_weight: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "side": self.side, "qty": self.qty,
            "est_value": round(self.est_value, 2),
            "from_weight": round(self.from_weight, 4),
            "to_weight": round(self.to_weight, 4),
            "reason": self.reason,
        }


def plan_orders(
    targets: dict[str, float],
    holdings: dict[str, int],
    prices: dict[str, float],
    portfolio_value: float,
    *,
    drift_band_pct: float = 3.0,
) -> list[OrderIntent]:
    """Diff current holdings against ``targets`` (symbol -> weight). A name
    only trades when |target − current| weight exceeds ``drift_band_pct``;
    a name that fell out of ``targets`` is always fully sold."""
    if portfolio_value <= 0:
        return []
    band = max(drift_band_pct, 0.0) / 100.0
    symbols = set(targets) | set(holdings)
    intents: list[OrderIntent] = []

    for sym in sorted(symbols):
        px = float(prices.get(sym) or 0.0)
        if px <= 0:
            continue
        cur_qty = int(holdings.get(sym, 0))
        cur_w = cur_qty * px / portfolio_value
        tgt_w = float(targets.get(sym, 0.0))
        drift = tgt_w - cur_w

        dropped = sym not in targets and cur_qty > 0
        if not dropped and abs(drift) < band:
            continue

        tgt_qty = 0 if sym not in targets else int(math.floor(tgt_w * portfolio_value / px))
        delta = tgt_qty - cur_qty
        if delta == 0:
            continue
        intents.append(
            OrderIntent(
                symbol=sym,
                side="BUY" if delta > 0 else "SELL",
                qty=abs(delta),
                est_value=abs(delta) * px,
                from_weight=cur_w,
                to_weight=tgt_w,
                reason="exit — dropped from target" if dropped else "rebalance to target",
            )
        )
    return intents
