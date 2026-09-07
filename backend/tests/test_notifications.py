"""Outbound notifications: enqueue filtering, Telegram delivery, event hooks."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from app.config import get_settings
from app.models.instrument import Instrument
from app.models.notifications import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    Notification,
)
from app.notifications import service
from app.notifications import telegram as tg
from app.paper_account import engine, pricing
from app.paper_account.engine import OrderRequest

# --------------------------------------------------------------------------
# helpers / fixtures
# --------------------------------------------------------------------------

def _enable(db, **over):
    cfg = service.get_config(db)
    cfg.enabled = True
    cfg.telegram_chat_id = "123456"
    for k, v in over.items():
        setattr(cfg, k, v)
    db.flush()
    return cfg


@pytest.fixture()
def _token(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "test-token", raising=False)
    return s


@pytest.fixture()
def _sent(monkeypatch):
    """Capture Telegram sends; succeed by default."""
    calls: list[tuple[str, str, str]] = []

    def _send(token, chat_id, text):
        calls.append((token, chat_id, text))

    monkeypatch.setattr(tg, "send_message", _send)
    return calls


class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict:
        return self._body


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, _url, json=None):  # noqa: A002
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


# --------------------------------------------------------------------------
# enqueue: master switch, per-kind toggle, grade filter
# --------------------------------------------------------------------------

def test_enqueue_skipped_when_disabled(db):
    service.enqueue(db, "PAPER_FILL", title="x", body="")
    row = db.query(Notification).one()
    assert row.status == STATUS_SKIPPED and "disabled" in (row.last_error or "")


def test_enqueue_grade_filter_drops_below_min(db):
    _enable(db, idea_min_grade="A")
    service.enqueue(db, "IDEA_NEW", title="B idea", body="", grade="B")
    service.enqueue(db, "IDEA_NEW", title="A idea", body="", grade="A")
    rows = {r.title: r.status for r in db.query(Notification).all()}
    assert rows == {"B idea": STATUS_SKIPPED, "A idea": STATUS_PENDING}


def test_enqueue_per_kind_toggle(db):
    _enable(db, notify_paper_fills=False)
    service.enqueue(db, "PAPER_FILL", title="fill", body="")
    service.enqueue(db, "IDEA_OUTCOME", title="out", body="")
    rows = {r.title: r.status for r in db.query(Notification).all()}
    assert rows == {"fill": STATUS_SKIPPED, "out": STATUS_PENDING}


def test_enqueue_never_raises_on_bad_session(db, monkeypatch):
    monkeypatch.setattr(service, "get_config", lambda _db: (_ for _ in ()).throw(RuntimeError("boom")))
    service.enqueue(db, "PAPER_FILL", title="x", body="")  # must not raise


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def test_dispatch_sends_and_marks_sent(db, _token, _sent):
    _enable(db)
    service.enqueue(db, "IDEA_OUTCOME", title="TARGET", body="", payload={"symbol": "INFY"})
    out = service.dispatch_pending(db, _token)
    row = db.query(Notification).one()
    assert out["sent"] == 1 and row.status == STATUS_SENT and row.sent_at is not None
    assert len(_sent) == 1 and _sent[0][1] == "123456"


def test_dispatch_marks_failed_on_telegram_error(db, _token, monkeypatch):
    _enable(db)

    def _boom(*_a):
        raise tg.TelegramError("chat not found")

    monkeypatch.setattr(tg, "send_message", _boom)
    service.enqueue(db, "PAPER_FILL", title="x", body="")
    service.dispatch_pending(db, _token)
    row = db.query(Notification).one()
    assert row.status == STATUS_FAILED and row.attempts == 1 and "chat not found" in row.last_error


def test_dispatch_skips_without_token(db, _sent, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "", raising=False)
    _enable(db)
    service.enqueue(db, "PAPER_FILL", title="x", body="")
    service.dispatch_pending(db, s)
    row = db.query(Notification).one()
    assert row.status == STATUS_SKIPPED and row.last_error == "no bot token"
    assert _sent == []


def test_send_test_roundtrip(db, _token, _sent):
    _enable(db)
    res = service.send_test(db, _token)
    assert res["ok"] is True and res["status"] == STATUS_SENT
    assert _sent and "Test notification" in _sent[0][2]


# --------------------------------------------------------------------------
# telegram client: response mapping
# --------------------------------------------------------------------------

def test_telegram_send_ok(monkeypatch):
    monkeypatch.setattr(tg.httpx, "Client", lambda *a, **k: _FakeClient(_FakeResp(200, {"ok": True, "result": {}})))
    tg.send_message("tok", "1", "<b>hi</b>")  # no raise


def test_telegram_send_4xx_raises(monkeypatch):
    monkeypatch.setattr(
        tg.httpx, "Client",
        lambda *a, **k: _FakeClient(_FakeResp(400, {"ok": False, "description": "bad request"})),
    )
    with pytest.raises(tg.TelegramError, match="bad request"):
        tg.send_message("tok", "1", "x")


def test_telegram_send_5xx_retries_then_raises(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_a: None)
    monkeypatch.setattr(
        tg.httpx, "Client",
        lambda *a, **k: _FakeClient(_FakeResp(503, {"ok": False})),
    )
    with pytest.raises(tg.TelegramError):
        tg.send_message("tok", "1", "x")


# --------------------------------------------------------------------------
# event hooks
# --------------------------------------------------------------------------

def test_tracker_resolution_enqueues_outcome(db, monkeypatch):
    import tests.test_market_scanner as tms

    _enable(db)
    tms._live_rec(db, tradingsymbol="ZZZ", instrument_token="55", entry=100.0,
                  stop_loss=95.0, target_1=110.0, horizon="INTRADAY")
    db.flush()
    from app.market_scanner import tracker as trk

    monkeypatch.setattr(trk, "_live_price", lambda _tok: 111.0)  # blows through target
    monkeypatch.setattr(trk.md, "get_client", lambda *a, **k: None)
    trk.run_tracker(db, get_settings(), now=datetime.now(trk.IST).replace(hour=11).astimezone(UTC))

    row = db.query(Notification).filter(Notification.kind == "IDEA_OUTCOME").one()
    assert row.status == STATUS_PENDING and row.payload["symbol"] == "ZZZ"
    assert row.payload["outcome"] == "TARGET"


def test_paper_fill_enqueues_notification(db, monkeypatch):
    px = {"NSE:RELIANCE": 1300.0}

    def _quotes(_db, _s, refs):
        return {r["ref"]: pricing.Quote(r["ref"], px.get(r["ref"]), None) for r in refs}

    monkeypatch.setattr(pricing, "quotes", _quotes)
    db.add(Instrument(instrument_token="738561", tradingsymbol="RELIANCE", name="Reliance",
                      exchange="NSE", segment="NSE", instrument_type="EQ", tick_size=0.05, active=True))
    _enable(db)
    db.flush()

    o = engine.place_order(db, get_settings(), OrderRequest("NSE", "RELIANCE", "BUY", 5, product="CNC"))
    assert o.status == "COMPLETE"
    row = db.query(Notification).filter(Notification.kind == "PAPER_FILL").one()
    assert row.status == STATUS_PENDING
    assert row.payload["symbol"] == "RELIANCE" and row.payload["side"] == "BUY"
    assert row.payload["source"] == "manual"


def test_paper_fill_not_enqueued_when_toggle_off(db, monkeypatch):
    px = {"NSE:RELIANCE": 1300.0}
    monkeypatch.setattr(
        pricing, "quotes",
        lambda _db, _s, refs: {r["ref"]: pricing.Quote(r["ref"], px.get(r["ref"]), None) for r in refs},
    )
    db.add(Instrument(instrument_token="738561", tradingsymbol="RELIANCE", name="Reliance",
                      exchange="NSE", segment="NSE", instrument_type="EQ", tick_size=0.05, active=True))
    _enable(db, notify_paper_fills=False)
    db.flush()

    engine.place_order(db, get_settings(), OrderRequest("NSE", "RELIANCE", "BUY", 5, product="CNC"))
    row = db.query(Notification).filter(Notification.kind == "PAPER_FILL").one()
    assert row.status == STATUS_SKIPPED


# --------------------------------------------------------------------------
# daily summary
# --------------------------------------------------------------------------

def test_daily_summary_sends_once_per_day(db, _token, _sent, monkeypatch):
    _enable(db)
    db.commit()
    after_close = datetime.now(service.IST).replace(hour=15, minute=40, second=0, microsecond=0)
    if after_close.weekday() >= 5:
        after_close = after_close.replace(day=after_close.day - (after_close.weekday() - 4))

    assert service.maybe_send_daily_summary(db, _token, now=after_close.astimezone(UTC)) is True
    assert service.maybe_send_daily_summary(db, _token, now=after_close.astimezone(UTC)) is False
    rows = db.query(Notification).filter(Notification.kind == "DAILY_SUMMARY").all()
    assert len(rows) == 1


def test_daily_summary_skipped_before_cutoff(db, _token):
    _enable(db)
    db.commit()
    morning = datetime.now(service.IST).replace(hour=10, minute=0).astimezone(UTC)
    assert service.maybe_send_daily_summary(db, _token, now=morning) is False


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------

def test_format_escapes_and_renders_each_kind():
    from app.notifications import format as fmt

    assert "&lt;script&gt;" in fmt.render("IDEA_NEW", "t", "b", {"symbol": "<script>", "direction": "LONG",
                                                                 "entry": 1, "stop_loss": 1, "target_1": 2})
    assert "SL" in fmt.render("IDEA_OUTCOME", "t", "b", {"symbol": "X", "outcome": "SL", "direction": "LONG"})
    assert "BUY" in fmt.render("PAPER_FILL", "t", "b", {"symbol": "X", "side": "BUY", "quantity": 5, "price": 10})
    assert "Paper account" in fmt.render("DAILY_SUMMARY", "t", "b", {"date": "2026-09-07"})
    assert "Test" in fmt.render("TEST", "t", "b", {})
