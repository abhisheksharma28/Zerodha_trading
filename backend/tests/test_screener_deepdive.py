"""Deep-dive: grounding facts, LLM call, JSON parse, cache + refresh."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.assistant import llm
from app.models.screener import ScreenerRating
from app.screener import deepdive


@pytest.fixture()
def _rating(db):
    r = ScreenerRating(
        symbol="ACME", name="Acme Ltd", sector="Industrials",
        verdict="BUY", confidence="HIGH", composite=71.0,
        value_score=60.0, quality_score=75.0, growth_score=80.0, technical_score=70.0,
        data_completeness=0.9, ltp=100.0, pct_from_52w_high=-8.0, pct_from_52w_low=40.0,
        metrics={"pe": 18.0, "pb": 3.0, "roe": 22.0}, factors={"value": []}, notes=None,
        as_of=datetime.now(UTC),
    )
    db.add(r)
    db.commit()
    return r


_GOOD = json.dumps({k: f"{k} text with a number 12.3" for k in deepdive._SECTION_KEYS} | {"verdict": "HOLD — composite 71, qualitative picture agrees, medium confidence."})


def test_unknown_symbol_is_reported(db):
    out = deepdive.generate(db, None, "NOPE")
    assert out["available"] is False and "not in the latest screen" in out["reason"]


def test_no_llm_provider_returns_facts_and_hint(db, _rating, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda s: (False, "Set A_KEY.", ""))
    out = deepdive.generate(db, None, "ACME")
    assert out["available"] is False
    assert out["reason"] == "Set A_KEY."
    assert out["facts"]["symbol"] == "ACME"
    assert out["facts"]["screener"]["composite_score"] == 71.0


def test_generates_parses_and_caches(db, _rating, monkeypatch):
    calls = {"n": 0}

    def _fake_complete(settings, *, system, messages, max_tokens):
        calls["n"] += 1
        assert "FACTS (JSON)" in messages[0]["content"]
        return f"```json\n{_GOOD}\n```"

    monkeypatch.setattr(llm, "configured", lambda s: (True, None, "fake/model"))
    monkeypatch.setattr(llm, "complete", _fake_complete)

    out = deepdive.generate(db, None, "ACME")
    assert out["available"] is True
    assert set(out["sections"]) == set(deepdive._SECTION_KEYS)
    assert out["verdict"] == "HOLD"
    assert out["model"] == "fake/model"
    assert calls["n"] == 1

    # second call served from cache — no new LLM call
    deepdive.generate(db, None, "ACME")
    assert calls["n"] == 1

    # refresh forces a regenerate
    deepdive.generate(db, None, "ACME", refresh=True)
    assert calls["n"] == 2


def test_unparseable_response_is_surfaced_not_crashed(db, _rating, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda s: (True, None, "fake/model"))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "sorry, I can't do that")
    out = deepdive.generate(db, None, "ACME")
    assert out["available"] is False
    assert "parseable JSON" in out["reason"]
    assert out["raw"].startswith("sorry")
