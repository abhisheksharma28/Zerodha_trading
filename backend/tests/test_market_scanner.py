"""Market Scanner - Phase 1: price-action structure reader + universe build."""

from __future__ import annotations

from app.market_scanner import features as feat_mod
from app.market_scanner import signals as sig_mod
from app.market_scanner import structure, universe
from app.models.instrument import Instrument


def _bars(seq: list[tuple[float, float, float, float]]) -> list[dict]:
    return [{"open": o, "high": h, "low": lo, "close": c, "volume": 1000} for o, h, lo, c in seq]


def _zigzag_bars(nodes: list[float], per: int = 3) -> list[dict]:
    """Turn a list of pivot prices into bars (``per`` bars per pivot) with a
    small intrabar drift so fractal swings form cleanly."""
    out: list[dict] = []
    for p in nodes:
        for k in range(per):
            j = k - 1
            out.append({"open": p, "high": p + 1.0 + 0.1 * j, "low": p - 1.0 + 0.1 * j,
                        "close": p + 0.05 * j, "volume": 1000})
    return out


def _uptrend_bars() -> list[dict]:
    return _zigzag_bars([100, 104, 100, 108, 103, 113, 107, 118, 112, 123, 117, 128, 122, 133])


def test_structure_reads_an_uptrend():
    rep = structure.analyse(_uptrend_bars(), left=2, right=2)
    assert rep.trend == "UP"
    assert rep.swing_high is not None and rep.swing_low is not None
    assert rep.swing_low < rep.swing_high


def test_structure_downtrend_is_symmetric():
    down = _zigzag_bars([133, 129, 133, 125, 130, 120, 126, 115, 121, 110, 116, 105, 111, 100])
    rep = structure.analyse(down, left=2, right=2)
    assert rep.trend == "DOWN"


def test_bullish_fvg_detected_and_unmitigated():
    # bar i low (105) strictly above bar i-2 high (103) -> bullish gap 103..105,
    # and no later bar trades back down into it.
    seq = [
        (100, 103, 99, 102),   # i-2  high = 103
        (102, 104, 101, 103),  # i-1
        (106, 110, 105, 109),  # i    low  = 105  -> gap 103..105
        (109, 112, 108, 111),
        (111, 114, 110, 113),
    ] * 8
    rep = structure.analyse(_bars(seq), min_bars=30)
    assert any(z.kind == "bullish" and abs(z.bottom - 103) < 1e-6 and abs(z.top - 105) < 1e-6
               for z in rep.fvgs)


def test_liquidity_sweep_high():
    # 25 quiet bars, then a spike whose wick pokes above the range but closes back in
    quiet = [(100, 101, 99, 100)] * 25
    sweep = [(100, 108, 99, 100)]  # high 108 >> prior 101, close 100 < 101
    rep = structure.analyse(_bars(quiet + sweep), min_bars=20)
    assert rep.liquidity_sweep == "high"


def test_structure_needs_minimum_bars():
    rep = structure.analyse(_bars([(100, 101, 99, 100)] * 5), min_bars=30)
    assert rep.trend == "RANGE"
    assert rep.notes and "bars" in rep.notes[0]


def _mk(db, **kw):
    row = Instrument(
        instrument_token=kw["instrument_token"], tradingsymbol=kw["tradingsymbol"],
        name=kw.get("name"), exchange=kw["exchange"], segment=kw["segment"],
        instrument_type=kw["instrument_type"], underlying=kw.get("underlying"),
        expiry=kw.get("expiry"), strike=kw.get("strike"), lot_size=kw.get("lot_size"),
        active=True,
    )
    db.add(row)
    return row


def test_universe_build(db):
    # an index + its options, one F&O single stock + its option, one plain equity,
    # and a bond that must be screened out of the broad tier.
    _mk(db, instrument_token="256265", tradingsymbol="NIFTY 50", name="NIFTY 50",
        exchange="NSE", segment="INDICES", instrument_type="EQ")
    _mk(db, instrument_token="9001", tradingsymbol="NIFTY25SEP25000CE", name="NIFTY",
        exchange="NFO", segment="NFO-OPT", instrument_type="CE", underlying="NIFTY", strike=25000)
    _mk(db, instrument_token="738561", tradingsymbol="RELIANCE", name="Reliance Industries",
        exchange="NSE", segment="NSE", instrument_type="EQ")
    _mk(db, instrument_token="9002", tradingsymbol="RELIANCE25SEP3000CE", name="RELIANCE",
        exchange="NFO", segment="NFO-OPT", instrument_type="CE", underlying="RELIANCE", strike=3000)
    _mk(db, instrument_token="500325", tradingsymbol="TCS", name="Tata Consultancy",
        exchange="NSE", segment="NSE", instrument_type="EQ")
    _mk(db, instrument_token="4774913", tradingsymbol="0MOFSL27-N3", name="Motilal bond",
        exchange="NSE", segment="NSE", instrument_type="EQ")
    db.flush()

    u = universe.build(db, core_max=40, broad_max=50)

    core_syms = {c.tradingsymbol for c in u.core}
    assert "NIFTY 50" in core_syms and "RELIANCE" in core_syms  # have options -> core
    assert "TCS" in {c.tradingsymbol for c in u.broad}           # no options -> broad
    assert not any("0MOFSL27" in c.tradingsymbol for c in u.all)  # bond screened out

    idx = [c for c in u.core if c.asset_class == "INDEX"]
    assert idx and all(c.has_options and c.underlying for c in idx)
    tokens = [c.instrument_token for c in u.core]
    assert len(tokens) == len(set(tokens))


# --------------------------------------------------------------------------
# Phase 2: features + signal engine
# --------------------------------------------------------------------------


def _trend_daily_bars(n=260, up=True, start=100.0, step=0.6, noise=1.2):
    bars, px = [], start
    for i in range(n):
        drift = step if up else -step
        px = max(5.0, px + drift + (noise if i % 3 == 0 else -noise / 2))
        o = px - (0.3 if up else -0.3)
        c = px
        h = max(o, c) + noise
        lo = min(o, c) - noise
        bars.append({"open": o, "high": h, "low": lo, "close": c, "volume": 100000 + i * 10,
                     "time": f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}"})
    return bars


def test_features_read_a_daily_uptrend():
    f = feat_mod.daily_features(_trend_daily_bars(up=True))
    assert f.ema_stack == "BULL"
    assert f.atr14 and f.atr14 > 0
    assert f.rsi14 is not None


def test_signal_emits_a_long_setup_in_an_uptrend():
    bars = _trend_daily_bars(up=True, step=0.5, noise=3.5)
    d = feat_mod.daily_features(bars)
    from app.market_scanner import structure as st
    s = st.analyse(bars, min_bars=30)
    inp = sig_mod.SignalInput(
        ltp=bars[-1]["close"], asset_class="EQUITY", has_options=True,
        daily=d, daily_structure=s, tick_size=0.05,
    )
    setup = sig_mod.evaluate(inp)
    assert setup is not None
    assert setup.direction == "LONG"
    assert setup.stop_loss < setup.entry < setup.target_1
    assert setup.rr >= 1.6
    assert setup.confidence <= 90
    assert setup.grade in ("A", "B", "C")
    assert setup.factors and any(f.group == "trend" for f in setup.factors)
    # every factor is explainable
    for fd in setup.factor_dicts():
        assert fd["name"] and fd["detail"] and fd["side"] in ("LONG", "SHORT")


def test_signal_returns_none_when_nothing_lines_up():
    # flat, noiseless series -> no trend, no structure, no setup
    flat = [{"open": 100, "high": 100.4, "low": 99.6, "close": 100, "volume": 1000,
             "time": f"2026-01-{1 + i % 27:02d}"} for i in range(120)]
    d = feat_mod.daily_features(flat)
    from app.market_scanner import structure as st
    s = st.analyse(flat, min_bars=30)
    inp = sig_mod.SignalInput(ltp=100.0, asset_class="EQUITY", has_options=False,
                              daily=d, daily_structure=s)
    assert sig_mod.evaluate(inp) is None


# --------------------------------------------------------------------------
# Phase 3-4: tracker lifecycle + service shape
# --------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.market_scanner import service as scan_service  # noqa: E402
from app.market_scanner import tracker as trk  # noqa: E402
from app.models.market_scanner import ScanRecommendation, ScanRun  # noqa: E402


def _live_rec(db, **over):
    base = {
        "exchange": "NSE", "tradingsymbol": "RELIANCE", "instrument_token": "738561",
        "segment": "NSE", "name": "Reliance", "asset_class": "EQUITY", "horizon": "SWING",
        "direction": "LONG", "setup_type": "Break-of-structure continuation",
        "setup_tags": ["bos", "ema_stack"], "ref_price": 1300.0, "entry": 1300.0,
        "entry_type": "MARKET", "stop_loss": 1270.0, "target_1": 1360.0, "target_2": 1400.0,
        "rr": 2.0, "atr": 20.0, "confidence": 70.0, "bias_score": 45.0,
        "factors": [{"name": "bos", "detail": "x", "weight": 10, "side": "LONG", "group": "structure"}],
        "status": "LIVE", "trading_day": datetime.now(trk.IST).date().isoformat(),
    }
    base.update(over)
    base.setdefault("entered_price", base["entry"])
    r = ScanRecommendation(**base)
    db.add(r)
    db.flush()
    return r


def test_tracker_resolves_target_sl_and_stale(db, monkeypatch):
    s = get_settings()
    win = _live_rec(db, tradingsymbol="AAA", instrument_token="1")
    loss = _live_rec(db, tradingsymbol="BBB", instrument_token="2")
    stale = _live_rec(db, tradingsymbol="CCC", instrument_token="3")
    db.flush()

    prices = {"1": 1365.0, "2": 1265.0}
    monkeypatch.setattr(trk, "_live_price", lambda tok: prices.get(str(tok)))
    monkeypatch.setattr(trk.md, "get_client", lambda *a, **k: None)

    out = trk.run_tracker(db, s, now=datetime.now(UTC).replace(hour=6))
    for r in (win, loss, stale):
        db.refresh(r)
    assert win.status == "EXPIRED" and win.outcome == "TARGET" and float(win.result_r) == 2.0
    assert loss.status == "EXPIRED" and loss.outcome == "SL" and float(loss.result_r) == -1.0
    assert stale.status == "LIVE" and stale.tracking_state == "STALE"
    assert out.resolved_target == 1 and out.resolved_sl == 1 and out.stale == 1


def test_tracker_eod_flattens_to_neutral(db, monkeypatch):
    s = get_settings()
    r = _live_rec(db, tradingsymbol="DDD", instrument_token="9", entry=1000.0,
                  stop_loss=980.0, target_1=1050.0)
    db.flush()
    monkeypatch.setattr(trk, "_live_price", lambda tok: 1012.0)
    monkeypatch.setattr(trk.md, "get_client", lambda *a, **k: None)
    now = datetime.now(trk.IST).replace(hour=15, minute=40).astimezone(UTC)
    out = trk.run_tracker(db, s, now=now)
    db.refresh(r)
    assert r.status == "EXPIRED" and r.outcome == "NEUTRAL"
    assert float(r.result_points) == 12.0 and out.resolved_neutral == 1


def test_service_recommendations_and_logbook_shape(db):
    run = ScanRun(started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                  data_available=True, universe_size=100, scanned=100, produced=1)
    db.add(run)
    db.flush()
    _live_rec(db, tradingsymbol="EEE", instrument_token="11", scan_run_id=run.id)
    _live_rec(db, tradingsymbol="FFF", instrument_token="12", status="EXPIRED",
              outcome="TARGET", result_pct=4.6, result_r=2.0, result_points=60.0,
              exit_at=datetime.now(UTC))
    db.flush()

    recs = scan_service.recommendations(db)
    assert recs["available"] is True
    assert recs["summary"]["live"] >= 1 and recs["summary"]["target"] >= 1
    assert any(r["tradingsymbol"] == "EEE" for r in recs["live"])
    assert all("disclaimer" in r and "factors" in r for r in recs["live"])

    lb = scan_service.logbook(db, page=1, page_size=10)
    assert lb["total"] >= 1
    assert lb["stats"]["win_rate_pct"] is not None
    assert "Break-of-structure continuation" in lb["setups"]


def test_trade_style_split_equity_vs_option():
    from app.market_scanner.signals import trade_style_for
    assert trade_style_for("SWING", "EQUITY") == "EQUITY_DELIVERY"
    assert trade_style_for("INTRADAY", "EQUITY") == "EQUITY_INTRADAY"
    assert trade_style_for("SWING", "INDEX") == "EQUITY_INTRADAY"


def test_persist_keeps_pop_and_overlay_on_option_cards_only(db):
    from types import SimpleNamespace

    from app.market_scanner import scanner as sc

    run = ScanRun(started_at=datetime.now(UTC), trigger="manual")
    db.add(run)
    db.flush()

    si = SimpleNamespace(
        exchange="NSE", tradingsymbol="RELIANCE", instrument_token="738561",
        segment="NSE", name="Reliance", underlying="RELIANCE", asset_class="EQUITY",
    )
    setup = SimpleNamespace(
        horizon="SWING", direction="LONG", setup_type="Golden-cross trend",
        setup_tags=["golden_cross"], entry=1300.0, entry_type="MARKET",
        stop_loss=1270.0, target_1=1360.0, target_2=1400.0, rr=2.0,
        atr=20.0, confidence=80.0, bias_score=50.0, score_detail={"grade": "A"},
        factor_dicts=lambda: [{"name": "golden_cross", "detail": "x", "weight": 15,
                               "side": "LONG", "group": "trend"}],
    )
    overlay = {"structure": "bull_call_spread", "pop": 0.41, "net_debit": 30.0,
               "legs": [], "expiry": "2026-09-29", "dte": 26}

    eq = sc._persist(db, run, si, setup, trade_style="EQUITY_DELIVERY", fv=None, day="2026-09-03")
    op = sc._persist(db, run, si, setup, trade_style="OPTION", fv=None,
                     day="2026-09-03", overlay=overlay)
    db.flush()
    assert eq.trade_style == "EQUITY_DELIVERY" and eq.pop is None and eq.option_overlay is None
    assert op.trade_style == "OPTION" and float(op.pop) == 0.41
    assert op.option_overlay["structure"] == "bull_call_spread"
    # both keep the underlying levels as the thesis to manage against
    assert float(op.entry) == 1300.0 and float(op.stop_loss) == 1270.0


# --------------------------------------------------------------------------
# strict scoring
# --------------------------------------------------------------------------

def test_strict_score_is_bounded_and_transparent():
    from app.market_scanner import structure as st

    up = _trend_daily_bars(up=True, step=0.5, noise=3.5)
    d = feat_mod.daily_features(up)
    setup = sig_mod.evaluate(sig_mod.SignalInput(
        ltp=up[-1]["close"], asset_class="EQUITY", has_options=True,
        daily=d, daily_structure=st.analyse(up, min_bars=30),
    ))
    assert setup is not None
    # the old engine pinned nearly everything at 95 - strict scoring must not
    assert 45.0 <= setup.confidence <= 90.0
    assert setup.grade in ("A", "B", "C")
    sd = setup.score_detail
    assert set(sd["sub_scores"]) == set(sd["weights"])
    assert "penalties" in sd and "raw" in sd


def test_strict_score_gates_out_a_marginal_setup():
    from app.market_scanner import structure as st

    # constant-drift trend, no pullback, RSI pinned -> extended entry, gated
    up = _trend_daily_bars(up=True, step=0.6, noise=0.8)
    d = feat_mod.daily_features(up)
    setup = sig_mod.evaluate(sig_mod.SignalInput(
        ltp=up[-1]["close"], asset_class="EQUITY", has_options=True,
        daily=d, daily_structure=st.analyse(up, min_bars=30),
    ))
    assert setup is None  # below min_confidence


def test_protective_hedge_only_for_long_fno_and_fails_soft(db):
    from types import SimpleNamespace

    from app.market_scanner import scanner as sc

    long_si = SimpleNamespace(underlying="RELIANCE", tradingsymbol="RELIANCE", has_options=True)
    short_setup = SimpleNamespace(direction="SHORT", stop_loss=2800.0, entry=2700.0, atr=45.0)
    assert sc._protective_hedge(db, long_si, short_setup) is None  # shorts get no protective put

    no_root = SimpleNamespace(underlying=None, tradingsymbol="XYZ", has_options=False)
    long_setup = SimpleNamespace(direction="LONG", stop_loss=90.0, entry=100.0, atr=3.0)
    assert sc._protective_hedge(db, no_root, long_setup) is None

    # a LONG F&O name with no option rows in the test DB -> graceful None, no raise
    assert sc._protective_hedge(db, long_si, long_setup) is None
