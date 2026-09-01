"""Stage-by-stage backtest diagnostic for the opening-breakout NSE strategy.

    python -m app.diagnose INFY RELIANCE --days 45 --timeframe 5m

Prints, for the given universe: DATA VALIDATION -> OPENING RANGE VALIDATION
-> RVOL WARMUP -> ATR WARMUP -> ENTRY SIGNAL COUNT -> TRADE COUNT, and if
there are zero trades it names the first stage that stopped the pipeline.
Never prints a bare "backtest completed — 0 trades".
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.trades import reconstruct_trades
from app.config import get_settings
from app.db.session import SessionLocal
from app.market_data.instruments import resolve_instrument_token
from app.services import broker_service
from app.strategies.base import Bar
from app.strategies.library import OpeningBreakoutUSStrategy

RVOL_LOOKBACK = 14
ATR_PERIOD = 14
_WARMUP_SESSIONS = max(RVOL_LOOKBACK, ATR_PERIOD) + 1


def _rule(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _fetch(symbols: list[str], timeframe: str, days: int) -> dict[str, list[Bar]]:
    from app.backtesting.timeframes import kite_interval

    db = SessionLocal()
    try:
        client = broker_service.build_authenticated_client(db, get_settings())
    finally:
        db.close()
    interval = kite_interval(timeframe)
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    out: dict[str, list[Bar]] = {}
    for sym in symbols:
        token, ts = resolve_instrument_token(sym)
        rows = client.get_historical_candles(token, interval, from_dt, to_dt)
        out[ts] = [
            Bar(timestamp=r[0], open=r[1], high=r[2], low=r[3], close=r[4],
                volume=r[5] if len(r) > 5 else 0, instrument=ts)
            for r in rows
        ]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", default=["INFY", "RELIANCE"])
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()
    symbols = args.symbols or ["INFY", "RELIANCE"]

    print(f"Diagnostic backtest | {', '.join(symbols)} | {args.timeframe} | {args.days}d lookback")
    candles = _fetch(symbols, args.timeframe, args.days)

    # ---------------- 1. DATA VALIDATION --------------------------------
    _rule("1. DATA VALIDATION")
    dq = validate_candles(candles, timeframe=args.timeframe)
    print(f"session_aware={dq['session_aware']}  ok(no hard errors)={dq['ok']}")
    for s in dq["per_symbol"]:
        print(
            f"  {s['symbol']:10} bars={s['bars']:>5}  trading_days={s.get('trading_days')}"
            f"  complete={s.get('complete_days')}  incomplete={s.get('incomplete_days')}"
            f"  missing_candles={s.get('missing_candles')}  dupes={s.get('duplicate_candles')}"
            f"  malformed={s.get('malformed_rows')}"
        )
        print(
            f"             first={s.get('first_candle')}  last={s.get('last_candle')}"
            f"  candles/day min/avg/max={s.get('min_candles_in_day')}/"
            f"{s.get('avg_candles_per_complete_day')}/{s.get('max_candles_in_day')}"
        )
        if s.get("gaps"):
            print(f"             genuine intraday gaps: {s['gaps'][:3]}{' …' if s['gap_count'] > 3 else ''}")
        if s.get("short_sessions"):
            print(f"             short/holiday sessions (not missing data): {len(s['short_sessions'])}")
    for e in dq["errors"]:
        print(f"  ERROR: {e}")
    for w in dq["warnings"]:
        print(f"  note: {w}")

    # ---------------- 2. OPENING RANGE VALIDATION ---------------------
    _rule("2. OPENING RANGE VALIDATION (09:15 candle present?)")
    or_ok = True
    for s in dq["per_symbol"]:
        miss = s.get("opening_range_missing_days", [])
        td = s.get("trading_days", 0)
        print(f"  {s['symbol']:10} OR present on {td - len(miss)}/{td} sessions"
              f"  {'-> OPENING_RANGE_DATA_MISSING: ' + ', '.join(miss[:5]) if miss else ''}")
        if miss:
            or_ok = False

    # ---------------- 3. RVOL WARMUP --------------------------------
    _rule(f"3. RVOL WARMUP (needs {RVOL_LOOKBACK} prior sessions before first trade)")
    warm_ok = True
    for s in dq["per_symbol"]:
        td = s.get("trading_days", 0)
        tradable = max(0, td - RVOL_LOOKBACK)
        print(f"  {s['symbol']:10} {td} sessions -> {tradable} potentially-tradable sessions"
              f"  {'  (INSUFFICIENT: extend the date range)' if tradable == 0 else ''}")
        if tradable == 0:
            warm_ok = False

    # ---------------- 4. ATR WARMUP -------------------------------
    _rule(f"4. ATR WARMUP (needs {ATR_PERIOD}+1 completed daily bars)")
    for s in dq["per_symbol"]:
        td = s.get("trading_days", 0)
        print(f"  {s['symbol']:10} {td} completed sessions -> ATR available from session "
              f"{_WARMUP_SESSIONS}  {'(OK)' if td >= _WARMUP_SESSIONS else '(INSUFFICIENT)'}")

    # ---------------- run the strategy --------------------------------
    params = OpeningBreakoutUSStrategy.resolve_params(
        {**OpeningBreakoutUSStrategy.presets()["balanced"], "square_off_time": "15:30"}
    )
    engine = BacktestEngine(OpeningBreakoutUSStrategy, params, 1_000_000.0,
                            cost_model=CostModel(CostConfig()))
    result = engine.run(candles)
    d = result.diagnostics
    sig = d.signals
    rejects = {k[len("reject:"):]: v for k, v in sig.items() if k.startswith("reject:")}

    _rule("5. ENTRY SIGNAL COUNT")
    print(f"  RVOL-qualified (cumulative across days): {sig.get('rvol_qualified', 0)}")
    print(f"  armed (top-N selected):                 {sig.get('armed', 0)}")
    print(f"  breakout entries emitted:               {sig.get('breakout_entry', 0)}")
    print(f"  orders submitted / fills:               {d.orders_submitted} / {d.fills}")
    if rejects:
        print("  selection/entry rejections:")
        for k, v in sorted(rejects.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v}")

    _rule("6. TRADE COUNT")
    mark = {s: b[-1].close for s, b in candles.items() if b}
    trades = reconstruct_trades(result.fills, fill_costs=[f.cost for f in result.fills],
                                mark_prices=mark)
    closed = [t for t in trades if not t.is_open]
    print(f"  fills={d.fills}  reconstructed_trades={len(trades)}  closed={len(closed)}")
    for t in closed[:8]:
        print(f"    {t.instrument:10} {t.direction:5} entry={t.entry_price} exit={t.exit_price} "
              f"net={t.net_pnl:.0f}")

    # ---------------- verdict -----------------------------------
    _rule("VERDICT")
    if closed:
        print(f"OK — {len(closed)} closed trades.")
        return
    if any(s.get("bars", 0) == 0 for s in dq["per_symbol"]):
        stage = "1 DATA — one or more symbols returned no candles"
    elif not warm_ok:
        stage = ("3 RVOL/ATR WARMUP — not enough prior sessions in the date range; "
                 f"need > {RVOL_LOOKBACK} trading days before the first tradable day")
    elif not or_ok and sig.get("armed", 0) == 0:
        stage = "2 OPENING RANGE — 09:15 candle missing on the candidate days"
    elif sig.get("armed", 0) == 0:
        stage = (f"5 SELECTION — no stock cleared the price/liquidity/ATR/RVOL/top-N gate. "
                 f"Rejections: {rejects or 'none recorded'}")
    elif sig.get("breakout_entry", 0) == 0:
        stage = (f"5 ENTRY — {sig.get('armed', 0)} armed, but price never closed beyond the "
                 "opening-range level in-session (no breakout)")
    elif d.fills == 0:
        stage = f"5 EXECUTION — {d.orders_submitted} orders, all rejected: {d.rejection_reasons}"
    else:
        stage = "6 TRADES — entries filled but none closed before the data ended"
    print(f"ZERO TRADES. First failing stage: {stage}")


if __name__ == "__main__":
    main()
