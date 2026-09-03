"""Multi-swing chart patterns read off the structure pivot sequence."""

from __future__ import annotations

from app.market_scanner import chart_patterns as cp
from app.market_scanner import structure as st


def _zigzag(nodes: list[float], per: int = 6) -> list[dict]:
    out: list[dict] = []
    for p in nodes:
        for k in range(per):
            j = k - per / 2
            out.append({"open": p, "high": p + 1.2 + 0.05 * j, "low": p - 1.2 + 0.05 * j,
                        "close": p + 0.03 * j, "volume": 1000})
    return out


def _drift(start: float, end: float, n: int = 8) -> list[dict]:
    step = (end - start) / n
    out: list[dict] = []
    px = start
    for _ in range(n):
        nxt = px + step
        hi, lo = max(px, nxt) + 0.3, min(px, nxt) - 0.3
        out.append({"open": px, "high": hi, "low": lo, "close": nxt, "volume": 1000})
        px = nxt
    return out


def _report(bars: list[dict]) -> cp.ChartPatternReport:
    s = st.analyse(bars, min_bars=30)
    return cp.analyse(bars, s)


# --------------------------------------------------------------------------

def test_double_top_confirms_on_the_break_of_the_middle_trough():
    bars = _zigzag([104, 100, 112, 101, 112]) + _drift(112, 96, 8)  # break below ~101
    rep = _report(bars)
    names = {p.name for p in rep.patterns}
    assert "double_top" in names
    dt = next(p for p in rep.patterns if p.name == "double_top")
    assert dt.direction == "BEARISH" and dt.status == "confirmed"
    assert dt.target < dt.breakout < dt.stop


def test_double_bottom_is_the_mirror():
    bars = _zigzag([108, 112, 100, 111, 100]) + _drift(100, 118, 8)  # break above ~111
    rep = _report(bars)
    db = next((p for p in rep.patterns if p.name == "double_bottom"), None)
    assert db is not None and db.direction == "BULLISH" and db.status == "confirmed"
    assert db.stop < db.breakout < db.target


def test_forming_double_top_is_not_confirmed():
    bars = _zigzag([104, 100, 112, 101, 112]) + _drift(112, 108, 6)  # holds above the trough
    rep = _report(bars)
    dt = next((p for p in rep.patterns if p.name == "double_top"), None)
    # either not detected, or detected but only "forming"
    assert dt is None or dt.status == "forming"


def test_head_and_shoulders_top():
    # L H L H L skeleton with a higher centre H and level shoulders, then a
    # close through the neckline
    bars = _zigzag([100, 110, 102, 118, 102, 110, 100]) + _drift(100, 90, 8)
    rep = _report(bars)
    hs = next((p for p in rep.patterns if p.name == "head_shoulders_top"), None)
    assert hs is not None and hs.direction == "BEARISH" and hs.status == "confirmed"
    assert hs.target < hs.breakout


def test_ascending_triangle_flat_top_rising_lows():
    bars = _zigzag([100, 112, 104, 112, 107, 112]) + _drift(112, 120, 6)  # break the flat top
    rep = _report(bars)
    at = next((p for p in rep.patterns if p.name == "ascending_triangle"), None)
    assert at is not None and at.direction == "BULLISH" and at.status == "confirmed"


def test_descending_triangle_flat_bottom_falling_highs():
    bars = _zigzag([116, 104, 112, 104, 108, 104]) + _drift(104, 96, 6)  # break the flat bottom
    rep = _report(bars)
    dt = next((p for p in rep.patterns if p.name == "descending_triangle"), None)
    assert dt is not None and dt.direction == "BEARISH" and dt.status == "confirmed"


def test_needs_enough_bars_and_pivots():
    assert _report([{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}] * 10).patterns == []


def test_report_is_json_serialisable():
    bars = _zigzag([104, 100, 112, 101, 112]) + _drift(112, 96, 8)
    d = _report(bars).as_dict()
    assert "patterns" in d
    if d["patterns"]:
        assert set(d["patterns"][0]) == {"name", "label", "direction", "status",
                                         "strength", "breakout", "target", "stop"}
