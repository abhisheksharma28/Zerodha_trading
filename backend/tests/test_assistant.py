"""The research assistant: grounding + the chat orchestration (the LLM call
itself is stubbed)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.assistant import context, llm, service
from app.config import get_settings
from app.core.exceptions import ValidationError
from app.market_scanner import tracker as trk
from app.models.market_scanner import ScanRecommendation


def test_detect_symbols_by_ticker_and_name():
    assert "RELIANCE" in context.detect_symbols("is RELIANCE a good 5-year hold?")
    assert "INFY" in context.detect_symbols("what about Infosys for the long term")
    assert context.detect_symbols("which sectors will do well") == []


def test_detect_sectors():
    got = context.detect_sectors("is the bank sector still a buy, and what about healthcare")
    assert "bank" in got and "healthcare" in got


def test_status_reports_not_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "openai", raising=False)
    monkeypatch.setattr(s, "assistant_openai_api_key", "", raising=False)
    st = service.status(s)
    assert st["available"] is False and "ASSISTANT_OPENAI_API_KEY" in st["reason"]
    assert st["provider"] == "openai"


def test_status_ok_for_ollama_without_a_key(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "ollama", raising=False)
    st = service.status(s)
    assert st["available"] is True and "ollama" in st["model"].lower()


def test_suggestions_are_offered():
    out = service.suggestions()
    assert len(out["suggestions"]) >= 4
    assert any("5 year" in s.lower() or "5-year" in s.lower() for s in out["suggestions"])


def test_chat_grounds_then_calls_the_model(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "openai", raising=False)
    monkeypatch.setattr(s, "assistant_openai_api_key", "test-key", raising=False)

    # a live engine idea for RELIANCE so the grounding block has something
    db.add(ScanRecommendation(
        exchange="NSE", tradingsymbol="RELIANCE", instrument_token="738561", segment="NSE",
        name="Reliance", asset_class="EQUITY", horizon="SWING", trade_style="EQUITY_DELIVERY",
        direction="LONG", setup_type="Break-of-structure continuation", setup_tags=[],
        ref_price=1300.0, entry=1300.0, entry_type="MARKET", stop_loss=1270.0, target_1=1360.0,
        rr=2.0, atr=20.0, confidence=72.0, bias_score=40.0, score_detail={"grade": "B"},
        factors=[], status="LIVE", trading_day=datetime.now(trk.IST).date().isoformat(),
    ))
    db.flush()

    captured: dict = {}

    def _fake_complete(_settings, *, system, messages, max_tokens=None):
        captured["system"] = system
        captured["messages"] = messages
        return "Thesis: solid. ...\n\nNot investment advice. Do your own due diligence."

    monkeypatch.setattr(llm, "complete", _fake_complete)

    out = service.chat(db, s, [{"role": "user", "content": "Is RELIANCE a good 5-year hold?"}])
    assert "Not investment advice" in out["reply"]
    assert out["grounding"]["symbols"] == ["RELIANCE"]
    assert out["grounding"]["had_data"] is True
    # the grounded platform data was appended to the user's last message
    assert "PLATFORM DATA:" in captured["messages"][-1]["content"]
    assert "Live engine idea: LONG" in captured["messages"][-1]["content"]
    assert "careful" in captured["system"]


def test_chat_rejects_empty_or_non_user_tail(db):
    s = get_settings()
    with pytest.raises(ValidationError):
        service.chat(db, s, [])
    with pytest.raises(ValidationError):
        service.chat(db, s, [{"role": "assistant", "content": "hi"}])


def test_complete_raises_when_no_key(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "gemini", raising=False)
    monkeypatch.setattr(s, "gemini_api_key", "", raising=False)
    with pytest.raises(llm.AssistantNotConfigured):
        llm.complete(s, system="x", messages=[{"role": "user", "content": "hi"}])


def test_unknown_provider_is_reported_not_crashed(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "bogus", raising=False)
    ok, reason, _ = llm.configured(s)
    assert ok is False and "bogus" in reason
