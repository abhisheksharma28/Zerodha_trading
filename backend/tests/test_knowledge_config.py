"""The Trading Ideas engine's runtime knowledge config (knowledge.yaml)."""

from __future__ import annotations

from app.market_scanner import knowledge as kb


def test_defaults_load_and_have_the_core_sections():
    for section in ("enabled", "score", "candle_weights", "chart_weights",
                    "force_index", "reflexivity", "news", "sector", "calendar", "graham"):
        assert section in kb.KB
    assert kb.get("score", "grade_a") == 74.0
    assert kb.enabled("news") is True


def test_deep_merge_only_overrides_the_given_keys(monkeypatch, tmp_path):
    yml = tmp_path / "knowledge.yaml"
    yml.write_text(
        "score:\n  min_confidence: 55.0\nenabled:\n  news: false\n"
        "candle_weights:\n  bull_marubozu: 12\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kb, "_YAML_PATH", yml)
    try:
        kb.reload()
        assert kb.get("score", "min_confidence") == 55.0
        assert kb.get("score", "grade_a") == 74.0            # untouched default
        assert kb.enabled("news") is False
        assert kb.get("candle_weights", "bull_marubozu") == 12
        assert kb.get("candle_weights", "hammer") == 9        # untouched default
    finally:
        monkeypatch.undo()
        kb.reload()


def test_a_broken_yaml_falls_back_to_defaults(monkeypatch, tmp_path):
    yml = tmp_path / "knowledge.yaml"
    yml.write_text("[ this: is not a mapping", encoding="utf-8")
    monkeypatch.setattr(kb, "_YAML_PATH", yml)
    try:
        kb.reload()
        assert kb.get("score", "min_confidence") == 45.0
    finally:
        monkeypatch.undo()
        kb.reload()


def test_min_confidence_flows_into_signalconfig(monkeypatch, tmp_path):
    from app.market_scanner.signals import SignalConfig

    yml = tmp_path / "knowledge.yaml"
    yml.write_text("score:\n  min_confidence: 61.0\n", encoding="utf-8")
    monkeypatch.setattr(kb, "_YAML_PATH", yml)
    try:
        kb.reload()
        assert SignalConfig().min_confidence == 61.0
    finally:
        monkeypatch.undo()
        kb.reload()


def test_disabling_a_group_drops_its_factors(monkeypatch, tmp_path):
    from app.market_scanner import chart_patterns as cp
    from app.market_scanner import signals as sig

    rep = cp.ChartPatternReport(patterns=[cp.ChartPattern(
        "double_bottom", "Double Bottom", "BULLISH", "confirmed", 0.8, 100.0, 120.0, 90.0, 3)])
    assert sig._chart_pattern_factors(rep)  # enabled by default

    yml = tmp_path / "knowledge.yaml"
    yml.write_text("enabled:\n  chart_patterns: false\n", encoding="utf-8")
    monkeypatch.setattr(kb, "_YAML_PATH", yml)
    try:
        kb.reload()
        assert sig._chart_pattern_factors(rep) == []
    finally:
        monkeypatch.undo()
        kb.reload()
