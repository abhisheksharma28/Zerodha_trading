"""Rebalance engine for a basket.

Pure functions, no DB / broker:

  ``resolve_targets(spec, bars_by_symbol, as_of, current_holdings=..., ...)``
      -> the target weight per symbol for a rebalance dated ``as_of``.
      Causal: only bars at or before ``as_of`` are looked at. Applies the
      per-sleeve rule (momentum-top-k or a multi-factor composite score),
      anti-churn hysteresis for names already held, the sleeve weighting
      scheme, per-name and global position caps, and a market-regime
      de-risk gate.

  ``plan_orders(targets, holdings, prices, portfolio_value, drift_band_pct)``
      -> the BUY/SELL diff needed to move current holdings to ``targets``,
      skipping names that have not drifted past the band (but always
      exiting names that dropped out of the target).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.baskets import factors as _f
from app.baskets.spec import _PRICE_FACTORS, BasketSpec, RuleSpec, SleeveSpec
from app.regime import classify as _regime_classify
from app.regime import exposure_scale as _regime_exposure
from app.regime import factor_tilt as _regime_tilt


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


def _volumes_upto(bars: list[Any], as_of: datetime) -> list[float]:
    out: list[float] = []
    for b in bars:
        if _as_dt(b.timestamp) <= as_of:
            out.append(float(getattr(b, "volume", 0) or 0))
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


def _pct_ranks(raw: dict[str, float]) -> dict[str, float]:
    """Map values to a 0..1 percentile rank (higher value -> higher rank)."""
    if not raw:
        return {}
    items = sorted(raw.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {k: i / (n - 1) for i, (k, _v) in enumerate(items)}


# --------------------------------------------------------------------------
# factor scores for the composite_score rule
# --------------------------------------------------------------------------

FundamentalsFn = Callable[[str], dict[str, float] | None]
"""symbol -> {"value": 0..100, "quality": 0..100, "growth": 0..100} or None."""


def _price_factor_raw(
    factor: str,
    closes: list[float],
    rule: RuleSpec,
    *,
    volumes: list[float] | None = None,
    market_closes: list[float] | None = None,
) -> float | None:
    """Raw value for a price factor in the composite score. Higher = better.
    Uses the multi-horizon factor library (app.baskets.factors)."""
    if factor == "momentum":
        return _f.momentum_composite(closes)
    if factor == "low_vol":
        return _f.low_vol_score(closes, min(rule.lookback, 90))
    if factor == "trend":
        return _f.trend_composite(closes, rule.trend_ma or 200)
    if factor == "rs":
        return _f.relative_strength(closes, market_closes, min(rule.lookback, 126))
    if factor == "volume":
        return _f.volume_trend(volumes or [], closes)
    return None


def _composite_scores(
    members: list[str],
    bars_by_symbol: dict[str, list[Any]],
    as_of: datetime,
    rule: RuleSpec,
    fundamentals_fn: FundamentalsFn | None,
    *,
    market_bars: list[Any] | None = None,
    regime: str | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """0..100 blended score per member from the rule's factor_weights, plus
    a per-member {factor: 0..100 rank} breakdown for explainability.

    Price factors (momentum / low_vol / trend / rs / volume) are computed
    from bars. Fundamental factors (value / quality / growth) only
    contribute when a ``fundamentals_fn`` is supplied (the live / paper
    path); in a backtest it is None and those weights are renormalised
    away. ``rs`` needs ``market_bars``; without it that weight drops out.
    ``regime`` (when supplied) tilts the weights toward the factors that
    work in that market state.
    """
    weights = dict(rule.factor_weights) or {"momentum": 0.6, "trend": 0.2, "low_vol": 0.2}
    if fundamentals_fn is None:
        weights = {f: w for f, w in weights.items() if f in _PRICE_FACTORS}
    if market_bars is None:
        weights.pop("rs", None)
    if not weights:
        weights = {"momentum": 1.0}
    wsum = sum(weights.values()) or 1.0
    weights = {f: w / wsum for f, w in weights.items()}
    if regime:
        weights = _regime_tilt(regime, weights)

    market_closes = _closes_upto(market_bars, as_of) if market_bars else None

    # per-factor raw values across members
    raw_by_factor: dict[str, dict[str, float]] = {}
    for factor in weights:
        vals: dict[str, float] = {}
        if factor in _PRICE_FACTORS:
            for m in members:
                closes = _closes_upto(bars_by_symbol[m], as_of)
                vols = _volumes_upto(bars_by_symbol[m], as_of) if factor == "volume" else None
                v = _price_factor_raw(
                    factor, closes, rule, volumes=vols, market_closes=market_closes
                )
                if v is not None:
                    vals[m] = v
        else:
            for m in members:
                fv = (fundamentals_fn(m) or {}) if fundamentals_fn else {}
                if factor in fv and fv[factor] is not None:
                    vals[m] = float(fv[factor])
        raw_by_factor[factor] = vals

    ranks_by_factor = {f: _pct_ranks(v) for f, v in raw_by_factor.items()}

    scores: dict[str, float] = {}
    breakdown: dict[str, dict[str, float]] = {}
    for m in members:
        num = 0.0
        wtot = 0.0
        row: dict[str, float] = {}
        for factor, w in weights.items():
            r = ranks_by_factor.get(factor, {}).get(m)
            if r is None:
                continue
            row[factor] = round(100.0 * r, 1)
            num += w * r
            wtot += w
        scores[m] = 100.0 * (num / wtot) if wtot > 0 else 0.0
        if row:
            breakdown[m] = row
    return scores, breakdown


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

@dataclass
class SleeveResolution:
    sleeve_id: str
    name: str
    target_pct: float
    selected: dict[str, float]  # symbol -> weight (fraction of the whole basket)
    scores: dict[str, float] = field(default_factory=dict)  # 0..100, when a scored rule ran
    factor_ranks: dict[str, dict[str, float]] = field(default_factory=dict)  # sym -> {factor: 0..100}
    cash_pct: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class ResolveResult:
    weights: dict[str, float]           # symbol -> fraction of the basket (sum <= 1)
    cash_weight: float
    per_sleeve: list[SleeveResolution]
    regime: str = "normal"             # "normal" | "risk_off"
    notes: list[str] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return sum(self.weights.values())

    def score_of(self, symbol: str) -> float | None:
        for s in self.per_sleeve:
            if symbol in s.scores:
                return s.scores[symbol]
        return None


def _member_metric(
    sleeve: SleeveSpec, bars_by_symbol: dict[str, list[Any]], as_of: datetime,
    fundamentals_fn: FundamentalsFn | None, *, market_bars: list[Any] | None = None,
    regime: str | None = None,
) -> tuple[dict[str, float], list[str], list[str], dict[str, dict[str, float]]]:
    """(-> score/ROC per member that passes entry gates, -> gate notes,
    -> members that failed only the trend/min-ROC gate,
    -> per-member factor-rank breakdown for a scored rule)."""
    rule = sleeve.rule
    have = [m for m in sleeve.members if bars_by_symbol.get(m)]
    notes: list[str] = []
    missing = [m for m in sleeve.members if not bars_by_symbol.get(m)]
    if missing:
        notes.append(f"no price history for {', '.join(missing)}")

    if rule.type == "composite_score":
        scores, breakdown = _composite_scores(
            have, bars_by_symbol, as_of, rule, fundamentals_fn,
            market_bars=market_bars, regime=regime,
        )
        # entry gate: trend filter + min-ROC still apply as hard screens
        passed: dict[str, float] = {}
        soft_fail: list[str] = []
        for m in have:
            closes = _closes_upto(bars_by_symbol[m], as_of)
            roc = _roc_pct(closes, rule.lookback)
            if roc is None:
                notes.append(f"{m}: <{rule.lookback} bars")
                continue
            if roc < rule.min_roc_pct or (
                rule.trend_ma > 0 and (_sma(closes, rule.trend_ma) or 0) > closes[-1]
            ):
                soft_fail.append(m)
                continue
            passed[m] = scores.get(m, 0.0)
        return passed, notes, soft_fail, {m: breakdown[m] for m in passed if m in breakdown}

    # momentum_top_k
    passed = {}
    soft_fail = []
    for m in have:
        closes = _closes_upto(bars_by_symbol[m], as_of)
        roc = _roc_pct(closes, rule.lookback)
        if roc is None:
            notes.append(f"{m}: <{rule.lookback} bars")
            continue
        if roc < rule.min_roc_pct:
            soft_fail.append(m)
            continue
        if rule.trend_ma > 0:
            ma = _sma(closes, rule.trend_ma)
            if ma is None or closes[-1] < ma:
                soft_fail.append(m)
                continue
        passed[m] = roc
    return passed, notes, soft_fail, {}


def _rank_members(
    sleeve: SleeveSpec,
    bars_by_symbol: dict[str, list[Any]],
    as_of: datetime,
    *,
    held: frozenset[str] = frozenset(),
    fundamentals_fn: FundamentalsFn | None = None,
    market_bars: list[Any] | None = None,
    regime: str | None = None,
) -> tuple[list[str], dict[str, float], list[str], dict[str, dict[str, float]]]:
    """Apply the sleeve rule with anti-churn hysteresis.

    -> (selected symbols, {symbol: metric/score}, notes, factor-rank breakdown)
    """
    rule = sleeve.rule
    if not rule.active:
        have = [m for m in sleeve.members if bars_by_symbol.get(m)]
        notes = []
        missing = [m for m in sleeve.members if not bars_by_symbol.get(m)]
        if missing:
            notes.append(f"no price history for {', '.join(missing)}")
        return have, {}, notes, {}

    metric, notes, soft_fail, breakdown = _member_metric(
        sleeve, bars_by_symbol, as_of, fundamentals_fn,
        market_bars=market_bars, regime=regime,
    )

    # rank everything that cleared the hard screens, best first
    ranked = sorted(metric.items(), key=lambda kv: kv[1], reverse=True)
    order = [m for m, _ in ranked]

    top_k = rule.top_k
    hold_k = rule.effective_hold_k
    selected: list[str] = []
    for i, m in enumerate(order):
        rank = i + 1
        if rank <= top_k:
            selected.append(m)
        elif rank <= hold_k and m in held:
            selected.append(m)  # hysteresis: keep an existing holding in the buffer zone
            notes.append(f"{m}: held in buffer (rank {rank} <= hold_k {hold_k})")

    # exit_roc_pct: force out a held name whose momentum has decayed past the
    # wider exit gate, even if it is still inside the buffer
    if rule.exit_roc_pct is not None:
        keep: list[str] = []
        for m in selected:
            closes = _closes_upto(bars_by_symbol[m], as_of)
            roc = _roc_pct(closes, rule.lookback)
            if m in held and roc is not None and roc < rule.exit_roc_pct:
                notes.append(f"{m}: exit — ROC {roc:.1f}% < exit_roc {rule.exit_roc_pct}%")
                continue
            keep.append(m)
        selected = keep

    if soft_fail and not selected:
        notes.append("rule cleared no members — sleeve goes to cash")
    return selected, metric, notes, {m: breakdown[m] for m in selected if m in breakdown}


def _weight_within_sleeve(
    sleeve: SleeveSpec, selected: list[str], metric: dict[str, float],
    bars_by_symbol: dict[str, list[Any]], as_of: datetime,
) -> dict[str, float]:
    """Fractions within the sleeve (sum to 1) per the weighting scheme,
    then the per-name ``max_weight_pct`` cap (as a fraction of the whole
    basket) with excess redistributed."""
    n = len(selected)
    if n == 0:
        return {}

    w = sleeve.weighting
    if w == "equal":
        frac = dict.fromkeys(selected, 1.0 / n)
    elif w == "score_weighted":
        raw = {m: max(metric.get(m, 0.0), 0.0) for m in selected}
        tot = sum(raw.values())
        frac = {m: v / tot for m, v in raw.items()} if tot > 0 else dict.fromkeys(selected, 1.0 / n)
    elif w == "inverse_vol":
        window = min(sleeve.rule.lookback, 90) if sleeve.rule.active else 90
        inv = {}
        for m in selected:
            vol = _daily_vol(_closes_upto(bars_by_symbol[m], as_of), window)
            inv[m] = 1.0 / vol if vol and vol > 1e-9 else 0.0
        tot = sum(inv.values())
        frac = {m: v / tot for m, v in inv.items()} if tot > 0 else dict.fromkeys(selected, 1.0 / n)
    elif w == "momentum_weighted":
        lb = sleeve.rule.lookback if sleeve.rule.active else 126
        raw = {m: max(_roc_pct(_closes_upto(bars_by_symbol[m], as_of), lb) or 0.0, 0.0) for m in selected}
        tot = sum(raw.values())
        frac = {m: v / tot for m, v in raw.items()} if tot > 0 else dict.fromkeys(selected, 1.0 / n)
    else:
        frac = dict.fromkeys(selected, 1.0 / n)

    # per-name cap, expressed as a fraction of the whole basket -> convert to
    # a fraction of this sleeve, then water-fill the excess onto the others
    if sleeve.max_weight_pct > 0 and sleeve.weight > 0:
        cap = (sleeve.max_weight_pct / 100.0) / sleeve.weight
        if cap < 1.0:
            frac = _waterfill_cap(frac, cap)
    return frac


def _waterfill_cap(frac: dict[str, float], cap: float) -> dict[str, float]:
    out = dict(frac)
    for _ in range(20):
        over = {m: v for m, v in out.items() if v > cap + 1e-9}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        for m in over:
            out[m] = cap
        room = {m: v for m, v in out.items() if v < cap - 1e-9}
        rtot = sum(room.values())
        if rtot <= 0:
            break
        for m in room:
            out[m] += excess * (out[m] / rtot)
    return out


def _sector_cap(
    weights: dict[str, float], cap: float
) -> tuple[dict[str, float], list[str]]:
    """Hold any one equity sector to <= ``cap`` of the whole basket.

    Over-cap sectors are scaled down proportionally in a single pass. The
    freed weight is placed into the under-cap equity sectors up to their
    remaining headroom; whatever does not fit stays in cash (the basket
    holds less equity — the right response to "too concentrated in one
    sector"). ETF / gold / bond / cash buckets are not equity sectors and
    are left untouched.
    """
    from app.baskets.sectors import is_equity_sector, sector_of

    buckets: dict[str, list[str]] = {}
    for m in weights:
        buckets.setdefault(sector_of(m), []).append(m)
    eq_sectors = {b for b in buckets if is_equity_sector(b)}
    totals = {b: sum(weights[m] for m in buckets[b]) for b in eq_sectors}
    over = {b for b in eq_sectors if totals[b] > cap + 1e-9}
    if not over:
        return weights, []

    out = dict(weights)
    notes: list[str] = []
    freed = 0.0
    for b in over:
        scale = cap / totals[b]
        for m in buckets[b]:
            freed += out[m] * (1.0 - scale)
            out[m] *= scale
        notes.append(f"sector cap: {b} trimmed {totals[b]:.0%} -> {cap:.0%}")

    headroom = {b: cap - totals[b] for b in eq_sectors if b not in over and totals[b] < cap}
    htot = sum(headroom.values())
    placed = min(freed, htot)
    if htot > 1e-9 and placed > 1e-12:
        for b, hr in headroom.items():
            add_b = placed * (hr / htot)
            btot = sum(out[m] for m in buckets[b]) or 1.0
            for m in buckets[b]:
                out[m] += add_b * (out[m] / btot)
    if freed - placed > 1e-4:
        notes.append(f"sector cap: {(freed - placed):.0%} of the basket held in cash")
    return out, notes


def resolve_targets(
    spec: BasketSpec,
    bars_by_symbol: dict[str, list[Any]],
    as_of: datetime | str,
    *,
    current_holdings: dict[str, int] | set[str] | None = None,
    fundamentals_fn: FundamentalsFn | None = None,
    market_bars: list[Any] | None = None,
) -> ResolveResult:
    """``market_bars`` is the basket benchmark's bar series; when supplied it
    powers the ``rs`` (relative strength) composite factor. Without it that
    factor's weight is renormalised away."""
    as_of_dt = _as_dt(as_of)
    held: frozenset[str] = frozenset(
        current_holdings if isinstance(current_holdings, (set, frozenset))
        else (k for k, v in (current_holdings or {}).items() if v)
    )

    # market regime: graduated exposure + regime-adaptive factor weights,
    # only for baskets that opted in via spec.risk.regime
    regime = "normal"
    risk_scale = 1.0
    notes: list[str] = []
    tilt_regime: str | None = None
    if spec.risk.regime is not None:
        gate = spec.risk.regime
        idx_bars = market_bars or bars_by_symbol.get(gate.benchmark)
        if idx_bars:
            state = _regime_classify(
                _closes_upto(idx_bars, as_of_dt), as_of_label=as_of_dt.date().isoformat()
            )
            regime = state.regime
            tilt_regime = state.regime
            risk_scale = _regime_exposure(
                state.regime, floor=gate.risk_off_scale, hard_cut=gate.hard_cut
            )
            notes.append(
                f"regime: {state.regime} (score {state.score:.0f}) — "
                f"risk-asset sleeves at {risk_scale:.0%}"
                + (f"; {state.drivers[0]}" if state.drivers else "")
            )

    weights: dict[str, float] = {}
    per_sleeve: list[SleeveResolution] = []

    for sleeve in spec.sleeves:
        selected, metric, s_notes, factor_ranks = _rank_members(
            sleeve, bars_by_symbol, as_of_dt, held=held,
            fundamentals_fn=fundamentals_fn, market_bars=market_bars,
            regime=tilt_regime,
        )
        within = _weight_within_sleeve(sleeve, selected, metric, bars_by_symbol, as_of_dt)
        scale = risk_scale if sleeve.risk_asset else 1.0
        sleeve_weights = {m: frac * sleeve.weight * scale for m, frac in within.items()}
        for m, wv in sleeve_weights.items():
            weights[m] = weights.get(m, 0.0) + wv
        filled = sum(sleeve_weights.values())
        cash_pct = max(sleeve.weight_pct - filled * 100.0, 0.0)
        scores = metric if sleeve.rule.type == "composite_score" else {}
        per_sleeve.append(
            SleeveResolution(
                sleeve_id=sleeve.id, name=sleeve.name, target_pct=sleeve.weight_pct,
                selected=sleeve_weights, scores={k: round(v, 1) for k, v in scores.items()},
                factor_ranks=factor_ranks, cash_pct=cash_pct, notes=s_notes,
            )
        )
        notes.extend(f"{sleeve.id}: {n}" for n in s_notes)

    # global single-name cap (fraction of the whole basket); excess is
    # water-filled onto the other invested names, not sent to cash
    cap = spec.risk.max_position_pct / 100.0
    if cap > 0 and weights and any(v > cap + 1e-9 for v in weights.values()):
        weights = _waterfill_cap(weights, cap)

    # sector concentration cap — hold any one equity sector to <= max_sector_pct
    sec_cap = spec.risk.max_sector_pct / 100.0
    if sec_cap > 0 and weights:
        weights, sec_notes = _sector_cap(weights, sec_cap)
        notes.extend(sec_notes)
        # re-apply the single-name cap: the redistribution may have pushed a
        # name back over it
        if cap > 0 and any(v > cap + 1e-9 for v in weights.values()):
            weights = _waterfill_cap(weights, cap)

    invested = sum(weights.values())
    return ResolveResult(
        weights=weights, cash_weight=max(1.0 - invested, 0.0),
        per_sleeve=per_sleeve, regime=regime, notes=notes,
    )


# --------------------------------------------------------------------------
# order planning
# --------------------------------------------------------------------------

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
    reasons: dict[str, str] | None = None,
) -> list[OrderIntent]:
    """Diff current holdings against ``targets`` (symbol -> weight). A name
    only trades when |target − current| weight exceeds ``drift_band_pct``;
    a name that fell out of ``targets`` is always fully sold. ``reasons``
    maps a symbol to a human explanation for the change log."""
    if portfolio_value <= 0:
        return []
    band = max(drift_band_pct, 0.0) / 100.0
    reasons = reasons or {}
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
        default = (
            "exit — dropped from target"
            if dropped
            else ("new position" if cur_qty == 0 else "rebalance to target weight")
        )
        intents.append(
            OrderIntent(
                symbol=sym,
                side="BUY" if delta > 0 else "SELL",
                qty=abs(delta),
                est_value=abs(delta) * px,
                from_weight=cur_w,
                to_weight=tgt_w,
                reason=reasons.get(sym, default),
            )
        )
    return intents
