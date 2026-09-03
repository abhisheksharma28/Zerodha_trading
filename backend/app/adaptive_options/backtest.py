"""Phase 14 — the adaptive-options backtest engine.

Walks trading days forward, and on each one runs the *same* pipeline used
live (data quality → engines → strategy selection → sizing → risk) to make
one decision, then manages the open structure with the leg manager. One
position at a time (v1). Fills go through the shared Indian options cost
model. No look-ahead: engine history is accumulated as the walk proceeds.

Data source per date: NSE F&O bhavcopy (real EOD OI) when it downloads,
otherwise a synthetic vol-surface chain — the result is flagged
``synthetic_data`` and ``source_breakdown`` records which dates used which.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.adaptive_options import (
    bhavcopy,
    confidence,
    data_quality,
    expected_move,
    leg_manager,
    local_history,
    pcr_engine,
    positioning,
    regime,
    risk_engine,
    sizing,
    strategy_selector,
    synthetic,
    volatility,
)
from app.adaptive_options import market_intelligence as mi_engine
from app.adaptive_options.chain_view import from_bhavcopy_rows
from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.strategy_library import build_position, get_template
from app.adaptive_options.types import ChainSnapshot
from app.backtesting.adhoc import fetch_candles
from app.backtesting.costs import CostConfig, CostModel
from app.config import Settings
from app.core.exceptions import ValidationError
from app.strategies.indicators import atr, rolling_volatility

_SPOT_SYM = {
    "NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
}
_LOT = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 140}
_SPREAD_FRAC = 0.02


@dataclass
class _Open:
    op: leg_manager.OpenPosition
    slug: str
    entry_date: date
    entry_legs: list
    entry_costs: float
    entry_margin: float
    entry_iv: float | None
    entry_confidence: float
    entry_regime: str
    mae: float = 0.0
    mfe: float = 0.0
    adjustments: int = 0


@dataclass
class AdaptiveBacktestResult:
    underlying: str
    start: str
    end: str
    config: dict[str, Any]
    synthetic_data: bool
    source_breakdown: dict[str, int]
    equity_curve: list[list[Any]]
    trades: list[dict[str, Any]]
    decision_log: list[dict[str, Any]]
    metrics: dict[str, Any]
    attribution: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying, "start": self.start, "end": self.end,
            "config": self.config, "synthetic_data": self.synthetic_data,
            "source_breakdown": self.source_breakdown,
            "equity_curve": self.equity_curve, "trades": self.trades,
            "decision_log": self.decision_log[-500:], "decision_log_len": len(self.decision_log),
            "metrics": self.metrics, "attribution": self.attribution,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------
# expiry + chain helpers
# --------------------------------------------------------------------------

def _bar_date(b: Any) -> date:
    return date.fromisoformat(str(getattr(b, "timestamp", ""))[:10])


def _weekly_expiry(d: date, min_dte: int = 3) -> tuple[date, int]:
    ahead = (3 - d.weekday()) % 7          # Thursday = 3
    if ahead < min_dte:
        ahead += 7
    return d + timedelta(days=ahead), ahead


def _monthly_expiry(d: date, min_dte: int = 3) -> tuple[date, int]:
    def _last_thu(y: int, m: int) -> date:
        nxt = date(y + (m == 12), (m % 12) + 1, 1)
        last = nxt - timedelta(days=1)
        while last.weekday() != 3:
            last -= timedelta(days=1)
        return last
    exp = _last_thu(d.year, d.month)
    if (exp - d).days < min_dte:
        nm, ny = (d.month % 12) + 1, d.year + (d.month == 12)
        exp = _last_thu(ny, nm)
    return exp, (exp - d).days


_TS_MIN = datetime.min.time()


def _bhav_snap(text: str, underlying: str, spot: float, expiry: date, dte: int, d: date):
    rows = bhavcopy.chain_rows(text, underlying, expiry, index_option=True)
    if len(rows) < 12:
        return None
    return from_bhavcopy_rows(underlying, expiry.isoformat(), spot,
                              datetime.combine(d, _TS_MIN), float(dte), rows)


def _local_snap(underlying: str, spot: float, expiry: date, dte: int, d: date):
    rows = local_history.chain_rows(underlying, d, expiry)
    if not rows or len(rows) < 12:
        return None
    return from_bhavcopy_rows(underlying, expiry.isoformat(), spot,
                              datetime.combine(d, _TS_MIN), float(dte), rows)


def _pick_bt_expiry(d: date, underlying: str, kind: str, source: str) -> tuple[date, int]:
    """Prefer the real listed expiries in the data source for this date; fall
    back to the synthetic Thursday calendar when the source has nothing."""
    listed: list[date] = []
    if source in ("local", "local_bhavcopy"):
        listed = local_history.expiries_on(underlying, d)
    if not listed and source in ("bhavcopy", "auto", "local_bhavcopy"):
        text = bhavcopy.download(d)
        if text:
            listed = bhavcopy.expiries_in(text, underlying, index_option=True)
    if listed:
        pool = listed
        if kind == "monthly":
            by_month: dict[tuple[int, int], date] = {}
            for e in listed:
                by_month[(e.year, e.month)] = max(by_month.get((e.year, e.month), e), e)
            pool = sorted(by_month.values())
        future = [e for e in pool if (e - d).days >= 3]
        if future:
            return future[0], (future[0] - d).days
    return _weekly_expiry(d) if kind == "weekly" else _monthly_expiry(d)


def _chain_for(
    d: date, underlying: str, spot: float, expiry: date, dte: int,
    source: str, synth_prev: ChainSnapshot | None, realized_vol: float | None,
) -> tuple[ChainSnapshot, str]:
    """source: synthetic | bhavcopy | auto (bhav→synth) | local (local→synth)
    | local_bhavcopy (local→bhav→synth)."""
    if source in ("local", "local_bhavcopy"):
        snap = _local_snap(underlying, spot, expiry, dte, d)
        if snap is not None:
            return snap, "local"
        if source == "local":
            base_iv = synthetic.anchor_iv(realized_vol)
            return synthetic.build_chain(underlying, spot, datetime.combine(d, _TS_MIN),
                                         float(dte), base_iv=base_iv, prev=synth_prev,
                                         seed=d.toordinal()), "synthetic"

    if source in ("bhavcopy", "auto", "local_bhavcopy"):
        text = bhavcopy.download(d)
        if text:
            snap = _bhav_snap(text, underlying, spot, expiry, dte, d)
            if snap is not None:
                return snap, "bhavcopy"
        if source == "bhavcopy":
            raise ValidationError(
                f"No bhavcopy chain for {underlying} {expiry} on {d} — the NSE archive "
                "download failed or was blocked. Use 'auto', 'local' or 'synthetic'.")

    base_iv = synthetic.anchor_iv(realized_vol)
    snap = synthetic.build_chain(
        underlying, spot, datetime.combine(d, _TS_MIN), float(dte),
        base_iv=base_iv, prev=synth_prev, seed=d.toordinal())
    return snap, "synthetic"


def _basket_cost(cm: CostModel, legs: list, lot_size: int, *, opening: bool) -> float:
    tot = 0.0
    for lg in legs:
        side = lg.side if opening else ("SELL" if lg.side == "BUY" else "BUY")
        mid = max(lg.entry_price, 0.05)
        raw = mid * (1 + _SPREAD_FRAC) if side == "BUY" else mid * (1 - _SPREAD_FRAC)
        fill = cm.fill_price_with_slippage(side, raw, segment="options")
        cb = cm.charge(side, fill, lg.lots * lot_size, "options", reference_price=mid)
        tot += cb.total
    return tot


def _mark(open_legs: list, snap: ChainSnapshot, lot_size: int) -> float:
    pnl = 0.0
    for lg in open_legs:
        row = min(snap.rows, key=lambda r: abs(r.strike - lg.strike))
        cur = (row.call_ltp if lg.right == "CE" else row.put_ltp) or 0.0
        if cur <= 0:
            cur = max(0.0, (snap.spot - lg.strike) if lg.right == "CE" else (lg.strike - snap.spot))
        pnl += lg.signed * lg.lots * lot_size * (cur - lg.entry_price)
    return pnl


def _short_strikes(legs: list) -> tuple[float | None, float | None, float | None, float | None]:
    sc = next((lg.strike for lg in legs if lg.right == "CE" and lg.side == "SELL"), None)
    sp = next((lg.strike for lg in legs if lg.right == "PE" and lg.side == "SELL"), None)
    lc = next((lg.strike for lg in legs if lg.right == "CE" and lg.side == "BUY"), None)
    lp = next((lg.strike for lg in legs if lg.right == "PE" and lg.side == "BUY"), None)
    return sc, sp, lc, lp


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def _metrics(capital: float, curve: list[list[Any]], trades: list[dict[str, Any]],
             ppy: int = 252) -> dict[str, Any]:
    if len(curve) < 2:
        return {"note": "not enough data"}
    eq = [row[1] for row in curve]
    rets = [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] > 0]
    total_return = eq[-1] / capital - 1.0
    years = max(len(curve) / ppy, 1e-6)
    cagr = (eq[-1] / capital) ** (1 / years) - 1.0 if eq[-1] > 0 else -1.0
    mean = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets)) if len(rets) > 1 else 0.0
    downside = [r for r in rets if r < 0]
    dd_dev = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    sharpe = (mean / sd * math.sqrt(ppy)) if sd > 0 else 0.0
    sortino = (mean / dd_dev * math.sqrt(ppy)) if dd_dev > 0 else 0.0
    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1.0 if peak > 0 else 0.0)
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gross_w = sum(t["net_pnl"] for t in wins)
    gross_l = -sum(t["net_pnl"] for t in losses)
    pnls = [t["net_pnl"] for t in trades]
    streak_w = streak_l = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w, cur_l = cur_w + 1, 0
        else:
            cur_l, cur_w = cur_l + 1, 0
        streak_w = max(streak_w, cur_w)
        streak_l = max(streak_l, cur_l)
    srt = sorted(pnls)
    var5 = srt[max(0, int(0.05 * len(srt)) - 1)] if srt else 0.0
    cvar5 = (sum(srt[:max(1, int(0.05 * len(srt)))]) / max(1, int(0.05 * len(srt)))) if srt else 0.0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "downside_deviation_pct": round(dd_dev * 100, 3),
        "total_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "avg_win": round(gross_w / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_l / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(pnls), 2) if pnls else 0.0,
        "largest_loss": round(min(pnls), 2) if pnls else 0.0,
        "max_consecutive_wins": streak_w,
        "max_consecutive_losses": streak_l,
        "avg_holding_days": round(sum(t["holding_days"] for t in trades) / len(trades), 1) if trades else 0.0,
        "total_adjustments": sum(t["adjustments"] for t in trades),
        "net_pnl": round(sum(pnls), 2),
        "total_costs": round(sum(t["costs"] for t in trades), 2),
        "value_at_risk_5pct": round(var5, 2),
        "conditional_var_5pct": round(cvar5, 2),
        "exposure_pct": round(100 * sum(t["holding_days"] for t in trades) / max(len(curve), 1), 1),
    }


def _attribution(trades: list[dict[str, Any]]) -> dict[str, Any]:
    def _grp(key: str) -> dict[str, Any]:
        out: dict[str, dict[str, float]] = {}
        for t in trades:
            k = str(t.get(key, "?"))
            g = out.setdefault(k, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            g["trades"] += 1
            g["net_pnl"] += t["net_pnl"]
            g["wins"] += 1 if t["net_pnl"] > 0 else 0
        return {k: {"trades": int(v["trades"]), "net_pnl": round(v["net_pnl"], 2),
                    "win_rate_pct": round(100 * v["wins"] / v["trades"], 1)}
                for k, v in out.items()}
    return {
        "by_strategy": _grp("strategy"),
        "by_regime_at_entry": _grp("regime_at_entry"),
        "by_weekday": _grp("entry_weekday"),
        "by_dte_bucket": _grp("dte_bucket"),
    }


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

def run_adaptive_backtest(
    db: Session,
    settings: Settings,
    *,
    underlying: str = "NIFTY",
    start: str,
    end: str,
    config: dict[str, Any] | None = None,
    preset: str = "balanced",
    expiry_kind: str = "weekly",       # weekly | monthly
    data_source: str = "synthetic",    # synthetic | bhavcopy | auto | local | local_bhavcopy
    target_frac: float = 0.5,
    stop_frac: float = 1.0,
    near_close_days: int = 1,
) -> dict[str, Any]:
    u = underlying.strip().upper()
    if u not in _SPOT_SYM:
        raise ValidationError(f"Adaptive Options backtest supports {', '.join(_SPOT_SYM)}.")
    cfg = AdaptiveConfig.from_dict(config, preset=preset)
    d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if d0 >= d1:
        raise ValidationError("start must be before end.")

    spot_sym = _SPOT_SYM[u]
    daily_map, _sk = fetch_candles(
        db, settings, symbols=[spot_sym], timeframe="1d",
        start=(d0 - timedelta(days=430)).isoformat(), end=d1.isoformat())
    daily = next(iter(daily_map.values()), [])
    if len(daily) < 120:
        return {"available": False, "reason": "Not enough underlying daily history for the window."}

    lot_size = _LOT.get(u, 50)
    cm = CostModel(CostConfig())
    capital = cfg.account_capital
    dates = [_bar_date(b) for b in daily if d0 <= _bar_date(b) <= d1]

    history: list[dict[str, Any]] = []
    synth_prev: ChainSnapshot | None = None
    last_snap: ChainSnapshot | None = None
    open_pos: _Open | None = None
    realized = 0.0
    equity_curve: list[list[Any]] = []
    trades: list[dict[str, Any]] = []
    decision_log: list[dict[str, Any]] = []
    src_count = {"synthetic": 0, "bhavcopy": 0, "local": 0}
    warnings: list[str] = []

    for d in dates:
        bars_upto = [b for b in daily if _bar_date(b) <= d]
        if len(bars_upto) < 90:
            continue
        dc = [float(b.close) for b in bars_upto]
        dh = [float(b.high) for b in bars_upto]
        dl = [float(b.low) for b in bars_upto]
        spot = dc[-1]
        rv_bar = rolling_volatility(dc, cfg.rv_lookback_days)
        realized_vol = rv_bar * math.sqrt(252.0) if rv_bar else None
        atr_pts = atr(dh, dl, dc, cfg.atr_period)

        expiry, dte = _pick_bt_expiry(d, u, expiry_kind, data_source)
        snap, src = _chain_for(d, u, spot, expiry, dte, data_source, synth_prev, realized_vol)
        src_count[src] = src_count.get(src, 0) + 1
        last_snap = snap
        if src == "synthetic":
            synth_prev = snap

        # --- engines (offline mirror of service._analyse) ---
        dq = data_quality.assess_chain(
            snap, cfg, now=datetime.combine(d, datetime.min.time(), tzinfo=UTC))
        intel = mi_engine.analyse(bars_upto, cfg)
        pcr_s = pcr_engine.analyse(snap, cfg, history=history[-60:])
        pos_s = positioning.analyse(snap, cfg,
                                    price_change_pct=(spot / dc[-2] - 1.0) * 100.0 if len(dc) > 1 else None,
                                    history=history[-60:])
        vol_s = volatility.analyse(
            snap, cfg, iv_history=[h["atm_iv"] for h in history if h.get("atm_iv")],
            realized_vol=realized_vol, adx=intel.adx, trend_strength=intel.trend_strength)
        em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=atr_pts,
                                   day_open=float(bars_upto[-1].open))
        conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
        reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                              expected_move=em, confidence=conf, data_ok=True)
        history.append({
            "oi_pcr": pcr_s.oi_pcr, "weighted_pcr": pcr_s.weighted_pcr, "spot": spot,
            "atm_iv": vol_s.atm_iv, "put_support": pos_s.put_support,
            "call_resistance": pos_s.call_resistance,
        })

        # --- manage an open position ---
        pos_pnl = None
        if open_pos is not None:
            pos_pnl = _mark(open_pos.entry_legs, snap, lot_size)
            open_pos.mae = min(open_pos.mae, pos_pnl)
            open_pos.mfe = max(open_pos.mfe, pos_pnl)
            act = leg_manager.evaluate(
                open_pos.op, cfg, snap=snap, regime=reg, pcr=pcr_s, intel=intel, vol=vol_s,
                current_pnl=pos_pnl, dte=dte)
            decision_log.append({"date": d.isoformat(), "phase": "manage", "regime": reg.label,
                                 "action": act.action, "strategy": open_pos.slug,
                                 "reason": act.reason, "position_pnl": round(pos_pnl, 2)})
            exit_now = act.action in ("FULL_EXIT", "PARTIAL_EXIT", "REDUCE_QTY") or dte <= near_close_days
            if act.action not in ("HOLD", "FULL_EXIT") and dte > near_close_days:
                open_pos.adjustments += 1
            if exit_now:
                exit_costs = _basket_cost(cm, open_pos.entry_legs, lot_size, opening=False)
                net = pos_pnl - open_pos.entry_costs - exit_costs
                realized += net
                trades.append({
                    "entry_date": open_pos.entry_date.isoformat(), "exit_date": d.isoformat(),
                    "strategy": open_pos.slug, "direction": open_pos.op.direction,
                    "regime_at_entry": open_pos.entry_regime,
                    "entry_weekday": open_pos.entry_date.strftime("%a"),
                    "dte_bucket": _dte_bucket((expiry - open_pos.entry_date).days),
                    "lots": open_pos.op.lots, "entry_net_premium": round(open_pos.op.entry_net_premium, 2),
                    "gross_pnl": round(pos_pnl, 2),
                    "costs": round(open_pos.entry_costs + exit_costs, 2),
                    "net_pnl": round(net, 2),
                    "return_on_margin_pct": round(100 * net / max(open_pos.entry_margin, 1.0), 2),
                    "holding_days": (d - open_pos.entry_date).days,
                    "adjustments": open_pos.adjustments,
                    "exit_reason": act.reason if dte > near_close_days else "near expiry",
                    "mae": round(open_pos.mae, 2), "mfe": round(open_pos.mfe, 2),
                    "entry_iv": round(open_pos.entry_iv, 4) if open_pos.entry_iv else None,
                    "entry_confidence": round(open_pos.entry_confidence, 1),
                })
                open_pos = None
                pos_pnl = 0.0

        # --- decide when flat ---
        if open_pos is None:
            sel = strategy_selector.rank(
                cfg, snap=snap, regime=reg, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                expected_move=em, confidence=conf, intel=intel, data_ok=dq.ok, far_expiry_ok=False)
            decision_log.append({
                "date": d.isoformat(), "phase": "select", "regime": reg.label,
                "direction": reg.direction, "confidence": round(conf.score, 1),
                "action": sel.action,
                "strategy": sel.top.slug if sel.top else None,
                "reason": sel.no_trade_reason or (sel.top.reasons[0] if sel.top else "no fit"),
            })
            if sel.action == "ENTER" and sel.top is not None:
                tmpl = get_template(sel.top.slug)
                levels = sel.top.strikes["levels"]
                pos1 = build_position(tmpl, levels, snap, lots=1, lot_size=lot_size,
                                      fallback_iv=vol_s.atm_iv or 0.13)
                sz = sizing.size(pos1, cfg, dte=dte)
                state = risk_engine.PortfolioState(
                    capital=capital, spot=spot, day_pnl=0.0,
                    open_capital_at_risk=0.0, open_margin=0.0)
                rk = risk_engine.check_entry(sz, pos1, cfg, state, data_ok=dq.ok, dte=dte)
                lots = int(sz.lots * rk.scale) if rk.ok else 0
                if lots > 0:
                    posN = build_position(tmpl, levels, snap, lots=lots, lot_size=lot_size,
                                          fallback_iv=vol_s.atm_iv or 0.13)
                    entry_costs = _basket_cost(cm, posN.legs, lot_size, opening=True)
                    sc, sp, lc, lp = _short_strikes(posN.legs)
                    op = leg_manager.OpenPosition(
                        slug=tmpl.slug, direction=tmpl.direction, lots=lots, lot_size=lot_size,
                        entry_spot=spot, entry_net_premium=posN.net_premium,
                        short_call=sc, short_put=sp, long_call=lc, long_put=lp,
                        entry_regime=reg.label, entry_pcr_state=pcr_s.state,
                        target_pnl=abs(posN.max_profit) * target_frac,
                        stop_pnl=-(abs(posN.max_loss) * stop_frac if not posN.undefined_risk
                                   else abs(posN.net_premium) * 2.0),
                        undefined_risk=posN.undefined_risk)
                    open_pos = _Open(
                        op=op, slug=tmpl.slug, entry_date=d, entry_legs=posN.legs,
                        entry_costs=entry_costs, entry_margin=posN.margin_estimate,
                        entry_iv=vol_s.atm_iv, entry_confidence=conf.score, entry_regime=reg.label)

        equity_curve.append([d.isoformat(), round(capital + realized + (pos_pnl or 0.0), 2)])

    # force-close at the end
    if open_pos is not None and equity_curve and last_snap is not None:
        last_d = dates[-1]
        exit_costs = _basket_cost(cm, open_pos.entry_legs, lot_size, opening=False)
        pnl = _mark(open_pos.entry_legs, last_snap, lot_size)
        net = pnl - open_pos.entry_costs - exit_costs
        realized += net
        trades.append({
            "entry_date": open_pos.entry_date.isoformat(), "exit_date": last_d.isoformat(),
            "strategy": open_pos.slug, "direction": open_pos.op.direction,
            "regime_at_entry": open_pos.entry_regime,
            "entry_weekday": open_pos.entry_date.strftime("%a"),
            "dte_bucket": "n/a", "lots": open_pos.op.lots,
            "entry_net_premium": round(open_pos.op.entry_net_premium, 2),
            "gross_pnl": round(pnl, 2), "costs": round(open_pos.entry_costs + exit_costs, 2),
            "net_pnl": round(net, 2),
            "return_on_margin_pct": round(100 * net / max(open_pos.entry_margin, 1.0), 2),
            "holding_days": (last_d - open_pos.entry_date).days, "adjustments": open_pos.adjustments,
            "exit_reason": "backtest end", "mae": round(open_pos.mae, 2), "mfe": round(open_pos.mfe, 2),
            "entry_iv": round(open_pos.entry_iv, 4) if open_pos.entry_iv else None,
            "entry_confidence": round(open_pos.entry_confidence, 1),
        })
        equity_curve[-1][1] = round(capital + realized, 2)

    if src_count.get("synthetic", 0) and data_source != "bhavcopy":
        warnings.append(
            f"{src_count['synthetic']} of {sum(src_count.values())} decision dates used a "
            "SYNTHETIC option chain — this run exercises the adaptive mechanics only and is "
            "not evidence the approach is profitable.")
    if not trades:
        warnings.append("No trades were taken — the engine stayed in NO_TRADE / WAIT for the "
                        "whole window under this config.")

    res = AdaptiveBacktestResult(
        underlying=u, start=d0.isoformat(), end=d1.isoformat(),
        config={"preset": cfg.risk_profile, **cfg.to_dict(),
                "expiry_kind": expiry_kind, "data_source": data_source,
                "target_frac": target_frac, "stop_frac": stop_frac},
        synthetic_data=src_count.get("synthetic", 0) > 0,
        source_breakdown=src_count,
        equity_curve=equity_curve,
        trades=trades,
        decision_log=decision_log,
        metrics=_metrics(capital, equity_curve, trades),
        attribution=_attribution(trades),
        warnings=warnings,
    )
    return {"available": True, **res.as_dict()}


def _dte_bucket(dte: int) -> str:
    return "0-3" if dte <= 3 else "4-7" if dte <= 7 else "8-15" if dte <= 15 else "16+"
