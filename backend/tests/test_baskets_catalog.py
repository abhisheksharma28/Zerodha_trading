"""The 12 flagship products — every spec is valid, well-formed and carries
the product-layer metadata the catalog needs."""

from __future__ import annotations

from app.baskets import catalog
from app.baskets.spec import FREQUENCIES, parse_spec

EXPECTED_KEYS = {
    "core-growth", "all-weather-wealth", "momentum-leaders", "adaptive-alpha",
    "growth-accelerators", "smallmid-smart-alpha", "quality-compounders",
    "defensive-leaders", "dynamic-sector-rotation", "india-consumption-growth",
    "dividend-income", "golden-wealth",
}


def test_catalog_has_exactly_twelve_distinct_flagship_products():
    products = catalog.flagship()
    assert len(products) == 12
    assert {p["key"] for p in products} == EXPECTED_KEYS


def test_every_flagship_spec_is_valid_and_balanced():
    for p in catalog.flagship():
        spec = parse_spec(p["spec"])  # raises on any bad spec
        assert 1 <= len(spec.sleeves) <= 12
        total = sum(s.weight_pct for s in spec.sleeves)
        assert abs(total - 100.0) < 0.5, (p["key"], total)


def test_no_duplicate_members_within_any_sleeve():
    for p in catalog.flagship():
        spec = parse_spec(p["spec"])
        for sl in spec.sleeves:
            assert len(set(sl.members)) == len(sl.members), (p["key"], sl.id)


def test_every_flagship_carries_product_metadata():
    for p in catalog.flagship():
        assert 1 <= p["risk_level"] <= 5
        assert p["category"] in catalog.CATEGORIES
        assert p["rebalance_frequency"] in FREQUENCIES
        assert p["objective"].strip()
        assert p["benchmark"].strip()
        assert p["horizon"].strip()
        assert p["investment_style"].strip()
        assert isinstance(p["how_it_works"], list) and p["how_it_works"]
        assert isinstance(p["differentiators"], list) and p["differentiators"]


def test_journeys_reference_only_real_flagship_keys():
    j = catalog.journeys()
    assert len(j) == 4
    for label, keys in j.items():
        assert keys, label
        for k in keys:
            assert k in EXPECTED_KEYS, (label, k)


def test_broad_equity_products_carry_a_sector_cap():
    caps = {}
    for p in catalog.flagship():
        spec = parse_spec(p["spec"])
        caps[p["key"]] = spec.risk.max_sector_pct
    for k in ("momentum-leaders", "adaptive-alpha", "growth-accelerators", "smallmid-smart-alpha"):
        assert caps[k] == 30.0, k
    assert caps["dynamic-sector-rotation"] == 40.0  # concentration is the point
    # thematic / multi-asset products are not sector-capped
    assert caps["quality-compounders"] == 0.0
    assert caps["golden-wealth"] == 0.0


def test_risk_levels_span_the_scale():
    levels = {p["risk_level"] for p in catalog.flagship()}
    assert levels == {1, 2, 3, 4, 5}


def test_renamed_away_from_ai():
    names = " ".join(p["name"].lower() for p in catalog.flagship())
    assert "ai " not in names and "ai alpha" not in names
    assert any(p["key"] == "adaptive-alpha" for p in catalog.flagship())
