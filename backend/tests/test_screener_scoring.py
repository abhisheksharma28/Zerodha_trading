"""Cross-sectional scoring: pillar ranks, verdict cuts, thin-data guard."""

from __future__ import annotations

from app.screener import scoring
from app.screener.metrics import StockMetrics


def _stock(sym: str, sector: str, **kw) -> StockMetrics:
    m = StockMetrics(symbol=sym, name=sym, sector=sector)
    for k, v in kw.items():
        setattr(m, k, v)
    m.fundamentals_ok = True
    m.technicals_ok = True
    return m


def _full_tech(m: StockMetrics) -> StockMetrics:
    # a plausible technical set so `completeness` clears the thin-data gate
    m.ltp = 100.0
    m.week52_high = 120.0
    m.week52_low = 70.0
    m.sma50 = 95.0
    m.sma200 = 90.0
    m.ret_6m = 8.0
    return m


def _universe() -> list[StockMetrics]:
    # 8 IT names spanning cheap+quality+growth -> expensive+weak
    out = []
    for i in range(8):
        m = _stock(
            f"IT{i}", "Technology",
            pe=12 + i * 6, pb=1.5 + i * 0.8, ps=1.0 + i * 0.6,
            roe=30 - i * 3, operating_margin=25 - i * 2, profit_margin=20 - i * 2,
            debt_equity=10 + i * 20, current_ratio=2.5 - i * 0.1,
            revenue_growth=25 - i * 4, earnings_growth=30 - i * 5,
        )
        _full_tech(m)
        out.append(m)
    return out


def test_cheap_quality_growth_name_scores_buy_and_expensive_weak_scores_avoid():
    ratings = {
        r.symbol: r
        for r in scoring.score_universe(_universe(), buy_min=66, avoid_max=40, min_completeness=0.5)
    }
    best, worst = ratings["IT0"], ratings["IT7"]
    assert best.composite > worst.composite
    assert best.verdict == "BUY"
    assert worst.verdict == "AVOID"
    # working is shown
    assert best.factors["value"] and best.factors["quality"]
    assert best.confidence in ("HIGH", "MEDIUM")


def test_loss_making_pe_is_not_treated_as_cheap():
    uni = _universe()
    uni[0].pe = -8.0  # IT0 now loss-making
    r = {x.symbol: x for x in scoring.score_universe(uni, buy_min=66, avoid_max=40, min_completeness=0.5)}
    pe_factor = next(f for f in r["IT0"].factors["value"] if f["metric"] == "P/E")
    assert pe_factor["score"] <= 15  # penalised, not rewarded


def test_thin_data_name_is_capped_at_hold_low_confidence():
    uni = _universe()
    thin = _stock("THIN", "Technology", pe=6.0)  # one metric only, no technicals
    thin.technicals_ok = False
    uni.append(thin)
    r = {x.symbol: x for x in scoring.score_universe(uni, buy_min=66, avoid_max=40, min_completeness=0.5)}
    assert r["THIN"].verdict == "HOLD"
    assert r["THIN"].confidence == "LOW"
    assert r["THIN"].notes is not None


def test_small_sector_falls_back_to_universe_peers():
    uni = _universe()
    uni.append(_full_tech(_stock("LONE", "Chemicals", pe=15, pb=2, roe=22, revenue_growth=18)))
    r = {x.symbol: x for x in scoring.score_universe(uni, buy_min=66, avoid_max=40, min_completeness=0.5)}
    assert r["LONE"].factors["peer_basis"] == "universe"
