"""TradingView-style technical rating from daily candles.

A faithful port of the per-stock "Investment recommendations" widget on
the Stock Detail page (`frontend/src/pages/StockDetailPage.tsx`), so the
Technical Ratings tab and that widget agree:

  Moving average gauge  — last close vs SMA20, EMA20, EMA50, EMA200
  Technical indicators  — RSI(14), MACD histogram, price vs 20-bar VWAP,
                          10-day ROC, Bollinger(20,2) position
  Overall               — all 9 signals; verdict from the net buy-minus-sell
                          ratio (>=0.5 Strong Buy, >=0.2 Buy, <=-0.5 Strong
                          Sell, <=-0.2 Sell, else Neutral)
"""

from __future__ import annotations

from typing import Any

from app.strategies.indicators import bollinger, ema, macd, roc, rsi, sma

_MIN_BARS = 60


def _verdict(net: int, total: int) -> str:
    r = net / total if total else 0.0
    if r >= 0.5:
        return "STRONG_BUY"
    if r >= 0.2:
        return "BUY"
    if r <= -0.5:
        return "STRONG_SELL"
    if r <= -0.2:
        return "SELL"
    return "NEUTRAL"


def _gauge(label: str, signals: list[int]) -> dict[str, Any]:
    buy = sum(1 for s in signals if s > 0)
    sell = sum(1 for s in signals if s < 0)
    return {
        "label": label,
        "buy": buy,
        "neutral": len(signals) - buy - sell,
        "sell": sell,
        "verdict": _verdict(buy - sell, len(signals)),
    }


def _cmp(a: float | None, b: float | None) -> int:
    if a is None or b is None:
        return 0
    return 1 if a > b else -1 if a < b else 0


def rate(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
) -> dict[str, Any] | None:
    if len(closes) < _MIN_BARS:
        return None
    price = closes[-1]

    ma_signals = [
        _cmp(price, sma(closes, 20)),
        _cmp(price, ema(closes, 20)),
        _cmp(price, ema(closes, 50)),
        _cmp(price, ema(closes, 200)),
    ]

    rv = rsi(closes, 14)
    macd_res = macd(closes)
    hist = macd_res[2] if macd_res else None
    bb = bollinger(closes, 20, 2.0)
    r10 = roc(closes, 10)

    tail = min(20, len(closes))
    vol_tail = volumes[-tail:]
    vwap20: float | None = None
    if sum(vol_tail) > 0:
        vwap20 = sum(c * v for c, v in zip(closes[-tail:], vol_tail, strict=True)) / sum(vol_tail)

    ti_signals = [
        0 if rv is None else -1 if rv > 70 else 1 if rv < 30 else 1 if rv > 55 else -1 if rv < 45 else 0,
        0 if hist is None else 1 if hist > 0 else -1,
        _cmp(price, vwap20),
        0 if r10 is None else 1 if r10 > 1.0 else -1 if r10 < -1.0 else 0,
        -1 if (bb and price > bb[2]) else 1 if (bb and price < bb[0]) else 0,
    ]

    ma = _gauge("Moving average", ma_signals)
    ti = _gauge("Technical indicators", ti_signals)
    overall = _gauge("General assessment", ma_signals + ti_signals)
    total = len(ma_signals) + len(ti_signals)
    net = overall["buy"] - overall["sell"]

    return {
        "verdict": overall["verdict"],
        "score": round(net / total, 3) if total else 0.0,
        "gauges": {"moving_average": ma, "technical_indicators": ti, "overall": overall},
        "signals": {
            "price_vs_sma20": ma_signals[0],
            "price_vs_ema20": ma_signals[1],
            "price_vs_ema50": ma_signals[2],
            "price_vs_ema200": ma_signals[3],
            "rsi14": ti_signals[0],
            "macd_hist": ti_signals[1],
            "price_vs_vwap20": ti_signals[2],
            "roc10": ti_signals[3],
            "bollinger20": ti_signals[4],
        },
        "readings": {
            "rsi14": round(rv, 1) if rv is not None else None,
            "macd_hist": round(hist, 3) if hist is not None else None,
            "roc10_pct": round(r10, 2) if r10 is not None else None,
            "vwap20": round(vwap20, 2) if vwap20 is not None else None,
        },
    }
