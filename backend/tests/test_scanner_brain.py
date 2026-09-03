"""The 'brain' inputs that sit around a chart: candlestick patterns,
sector strength, the calendar bias and the news-headline heuristic - and
how they fold into the strict signal score."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.market_scanner import candles as cnd
from app.market_scanner import context as ctx
from app.market_scanner import features as feat_mod
from app.market_scanner import signals as sig_mod
from app.market_scanner import structure as st

IST = ZoneInfo("Asia/Kolkata")


def _bar(o: float, h: float, lo: float, c: float) -> dict:
    return {"open": o, "high": h, "low": lo, "close": c, "volume": 1000}


def _down_run(n: int, start: float = 120.0, step: float = 1.1) -> list[dict]:
    out, px = [], start
    for _ in range(n):
        nxt = px - step
        out.append(_bar(px, px + 0.4, nxt - 0.4, nxt))
        px = nxt
    return out


def _up_run(n: int, start: float = 100.0, step: float = 1.1) -> list[dict]:
    out, px = [], start
    for _ in range(n):
        nxt = px + step
        out.append(_bar(px, nxt + 0.4, px - 0.4, nxt))
        px = nxt
    return out


# --------------------------------------------------------------------------
# candlestick detectors
# --------------------------------------------------------------------------

def test_hammer_needs_a_downtrend_and_a_long_lower_wick():
    bars = _down_run(14, start=120.0)          # closes fall ~120 -> 104.6
    bars.append(_bar(104.6, 104.9, 101.2, 104.8))  # tiny body, 3.4 lower wick
    rep = cnd.analyse(bars)
    assert rep.trend == "DOWN"
    names = {p.name for p in rep.patterns}
    assert "hammer" in names
    ham = next(p for p in rep.patterns if p.name == "hammer")
    assert ham.direction == "BULLISH" and 0.0 < ham.strength <= 1.0


def test_same_shape_in_an_uptrend_is_a_hanging_man():
    bars = _up_run(14, start=100.0)
    bars.append(_bar(115.4, 115.7, 112.0, 115.6))
    rep = cnd.analyse(bars)
    assert rep.trend == "UP"
    assert any(p.name == "hanging_man" and p.direction == "BEARISH" for p in rep.patterns)


def test_bullish_marubozu_regardless_of_trend():
    bars = _down_run(14, start=120.0)
    # near-shadowless full green body, range ~2.7% of price
    bars.append(_bar(103.0, 105.85, 102.95, 105.8))
    rep = cnd.analyse(bars)
    m = next((p for p in rep.patterns if p.name == "bull_marubozu"), None)
    assert m is not None and m.direction == "BULLISH"
    assert m.entry == 105.8 and m.stop == 102.95  # buy the close, stop the low


def test_bearish_marubozu():
    bars = _up_run(14, start=100.0)
    bars.append(_bar(115.0, 115.05, 111.9, 112.0))  # full red body, tiny wicks
    rep = cnd.analyse(bars)
    m = next((p for p in rep.patterns if p.name == "bear_marubozu"), None)
    assert m is not None and m.direction == "BEARISH" and m.stop == 115.05


def test_marubozu_rejects_an_over_extended_candle():
    bars = _down_run(14, start=200.0)
    bars.append(_bar(180.0, 205.0, 179.5, 204.5))  # >12% range -> skipped (stop too deep)
    rep = cnd.analyse(bars)
    assert not any(p.name in ("bull_marubozu", "bear_marubozu") for p in rep.patterns)


def test_spinning_top_flags_indecision_in_a_trend():
    bars = _up_run(14, start=100.0)
    bars.append(_bar(115.0, 117.4, 112.6, 115.3))  # small body, ~equal 2.1/2.4 shadows
    rep = cnd.analyse(bars)
    s = next((p for p in rep.patterns if p.name == "spinning_top"), None)
    assert s is not None and s.direction == "BEARISH" and s.strength < 0.5


def test_bullish_engulfing_in_a_downtrend():
    bars = _down_run(13, start=120.0)
    bars.append(_bar(106.0, 106.3, 103.6, 104.0))   # red, body 2.0
    bars.append(_bar(103.5, 107.4, 103.2, 107.0))   # green, body 3.5, engulfs
    rep = cnd.analyse(bars)
    assert any(p.name == "bullish_engulfing" and p.direction == "BULLISH" for p in rep.patterns)


def test_evening_star_in_an_uptrend():
    bars = _up_run(12, start=100.0)
    bars.append(_bar(112.0, 117.2, 111.8, 117.0))   # a: big green
    bars.append(_bar(117.6, 118.2, 117.2, 117.5))   # b: small body, gapped up
    bars.append(_bar(117.0, 117.3, 112.4, 112.8))   # c: red, closes below a's midpoint
    rep = cnd.analyse(bars)
    assert any(p.name == "evening_star" and p.direction == "BEARISH" for p in rep.patterns)


def test_no_pattern_without_enough_bars():
    assert cnd.analyse([_bar(100, 101, 99, 100)] * 6).patterns == []


def test_report_as_dict_is_json_friendly():
    bars = _down_run(14, start=120.0)
    bars.append(_bar(104.6, 104.9, 101.2, 104.8))
    d = cnd.analyse(bars).as_dict()
    assert d["trend"] == "DOWN"
    assert d["patterns"] and set(d["patterns"][0]) == {
        "name", "label", "direction", "strength", "entry", "stop"
    }


# --------------------------------------------------------------------------
# calendar bias
# --------------------------------------------------------------------------

def test_calendar_bias_flags_the_turn_of_month():
    nudge, why = ctx.calendar_bias(datetime(2026, 9, 1, 10, 0, tzinfo=IST))
    assert nudge > 0 and "turn-of-month" in why


def test_calendar_bias_soft_in_the_deep_second_half():
    nudge, _ = ctx.calendar_bias(datetime(2026, 9, 22, 10, 0, tzinfo=IST))
    assert nudge < 0


def test_calendar_bias_is_neutral_mid_month():
    nudge, why = ctx.calendar_bias(datetime(2026, 9, 17, 10, 0, tzinfo=IST))
    assert nudge == 0.0 and why == ""


# --------------------------------------------------------------------------
# sector strength (market-overview driven)
# --------------------------------------------------------------------------

def _fake_overview(*_a, **_k) -> dict:
    return {
        "sectors": [
            {"sector": "Energy", "avg_change_pct": 2.4},
            {"sector": "IT", "avg_change_pct": 0.1},
            {"sector": "FMCG", "avg_change_pct": -0.2},
            {"sector": "Realty", "avg_change_pct": -1.9},
        ],
        "heatmap": [
            {"symbol": "RELIANCE", "sector": "Energy"},
            {"symbol": "INFY", "sector": "IT"},
            {"symbol": "DLF", "sector": "Realty"},
        ],
    }


def test_sector_nudge_resolves_symbol_and_scores_leaders_and_laggards(db, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(ctx.market_data_service, "market_overview", _fake_overview)
    ctx.clear_caches()
    s = get_settings()

    lead = ctx.sector_nudge_for(db, s, "RELIANCE")
    lag = ctx.sector_nudge_for(db, s, "DLF")
    mid = ctx.sector_nudge_for(db, s, "INFY")
    unknown = ctx.sector_nudge_for(db, s, "NOTLISTED")

    assert lead and lead[0] > 0 and "leading" in lead[1]
    assert lag and lag[0] < 0 and "lagging" in lag[1]
    assert mid and mid[0] == 0.0
    assert unknown is None
    ctx.clear_caches()


# --------------------------------------------------------------------------
# news headline heuristic
# --------------------------------------------------------------------------

class _Res:
    def __init__(self, data):
        self.available = True
        self.data = data


class _Prov:
    def __init__(self, data):
        self._data = data

    def get_news(self, _symbol):
        return _Res(self._data)


def test_news_signal_scores_recent_positive_headlines(monkeypatch):
    from app.config import get_settings

    now = datetime.now().timestamp()
    data = [
        {"title": "Company bags order worth Rs 5000 cr, brokerage target raised",
         "publisher": "X", "link": "l", "published": now - 3600},
        {"title": "Board approves buyback", "publisher": "Y", "link": "l", "published": now - 7200},
    ]
    monkeypatch.setattr(ctx, "get_fundamentals_provider", lambda _s: _Prov(data))
    ctx.clear_caches()
    sig = ctx.news_signal(get_settings(), "ABC")
    assert sig.score > 0 and sig.headlines and "not sentiment" in sig.note
    ctx.clear_caches()


def test_news_signal_scores_recent_negative_headlines(monkeypatch):
    from app.config import get_settings

    now = datetime.now().timestamp()
    data = [
        {"title": "SEBI probe into accounting; CFO resigns", "publisher": "X",
         "link": "l", "published": now - 3600},
        {"title": "Brokerage downgrade after profit falls", "publisher": "Y",
         "link": "l", "published": now - 7200},
    ]
    monkeypatch.setattr(ctx, "get_fundamentals_provider", lambda _s: _Prov(data))
    ctx.clear_caches()
    sig = ctx.news_signal(get_settings(), "XYZ")
    assert sig.score < 0
    ctx.clear_caches()


def test_news_signal_empty_when_no_headlines(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(ctx, "get_fundamentals_provider", lambda _s: _Prov([]))
    ctx.clear_caches()
    sig = ctx.news_signal(get_settings(), "NONE")
    assert sig.score == 0.0 and sig.headlines == []
    ctx.clear_caches()


# --------------------------------------------------------------------------
# how the brain inputs fold into the signal score
# --------------------------------------------------------------------------

def _trend_daily_bars(n=260, up=True, start=100.0, step=0.5, noise=3.0):
    bars, px = [], start
    for i in range(n):
        drift = step if up else -step
        px = max(5.0, px + drift + (noise if i % 3 == 0 else -noise / 2))
        o = px - (0.3 if up else -0.3)
        c = px
        bars.append({"open": o, "high": max(o, c) + noise, "low": min(o, c) - noise,
                     "close": c, "volume": 100000 + i * 10,
                     "time": f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}"})
    return bars


def _uptrend_input(**extra) -> sig_mod.SignalInput:
    bars = _trend_daily_bars(up=True)
    return sig_mod.SignalInput(
        ltp=bars[-1]["close"], asset_class="EQUITY", has_options=True,
        daily=feat_mod.daily_features(bars), daily_structure=st.analyse(bars, min_bars=30),
        tick_size=0.05, **extra,
    )


def test_candlestick_factor_appears_when_a_pattern_is_supplied():
    rep = cnd.CandleReport(patterns=[cnd.Pattern(
        "bullish_engulfing", "Bullish Engulfing", "BULLISH", 0.9, 100.0, 96.0, -1)], trend="DOWN")
    setup = sig_mod.evaluate(_uptrend_input(daily_candles=rep))
    assert setup is not None
    assert any(f.group == "candlestick" for f in setup.factors)


def test_context_and_news_factors_are_attached_and_signed():
    setup = sig_mod.evaluate(_uptrend_input(
        sector_nudge=(0.6, "Energy sector is leading the market today"),
        calendar_nudge=(0.7, "turn-of-month window (historically higher mean returns)"),
        news=ctx.NewsSignal(0.6, [{"title": "order win"}], "headline signal"),
    ))
    assert setup is not None
    groups = {f.group for f in setup.factors}
    assert "context" in groups and "news" in groups
    news_f = next(f for f in setup.factors if f.group == "news")
    assert news_f.weight > 0  # positive headlines -> long-side weight


def test_a_weak_negative_news_score_is_ignored():
    setup = sig_mod.evaluate(_uptrend_input(
        news=ctx.NewsSignal(0.1, [{"title": "minor"}], "headline signal")))
    assert setup is not None
    assert not any(f.group == "news" for f in setup.factors)
