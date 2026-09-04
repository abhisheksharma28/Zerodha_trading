# Baskets rebuild — Phase 1 report

Scope of Phase 1: the **product / config layer**. Turn the 26 mixed
templates into 12 flagship investment products with a professional
presentation surface, named universes, and the three safe correctness
fixes. The factor engine, regime engine, portfolio-construction and
data-quality work are Phases 2–6.

## What shipped

### 1. The 12-product catalog — `backend/app/baskets/catalog.py`

| # | Product | Category | Risk | Rebalance | Benchmark |
|---|---|---|---|---|---|
| 1 | Core Growth | Core | 3 | quarterly | NIFTY 50 |
| 2 | All Weather Wealth | Multi-Asset | 2 | quarterly | NIFTY 50 |
| 3 | Momentum Leaders | Smart Alpha | 4 | monthly | NIFTY 50 |
| 4 | **Adaptive Alpha** (was "AI Alpha Opportunities") | Smart Alpha | 5 | monthly | NIFTY 500 |
| 5 | Growth Accelerators | Growth | 4 | quarterly | NIFTY 500 |
| 6 | Small & Midcap Smart Alpha | Growth | 5 | monthly | NIFTY MIDCAP 150 |
| 7 | Quality Compounders | Defensive & Quality | 3 | quarterly | NIFTY 100 |
| 8 | Defensive Leaders | Defensive & Quality | 2 | quarterly | NIFTY 50 |
| 9 | Dynamic Sector Rotation | Thematic & Sector | 4 | monthly | NIFTY 50 |
| 10 | India Consumption Growth | Thematic & Sector | 4 | monthly | NIFTY 50 |
| 11 | Dividend & Income | Income | 2 | quarterly | NIFTY 50 |
| 12 | Golden Wealth | Multi-Asset | 1 | quarterly | NIFTY 50 |

Each product carries: `objective`, `investor_profile`, `horizon`,
`investment_style`, `holdings`, `risk_level` (1–5), `how_it_works` (bullet
list), `differentiators` (bullet list), the quant `spec`, and the
goal-journeys it belongs to.

New 7-category taxonomy: Core / Smart Alpha / Growth / Defensive & Quality
/ Thematic & Sector / Income / Multi-Asset.

Goal-based marketplace grouping (`journeys`):
- *I'm new to investing* → Core Growth, All Weather Wealth, Golden Wealth
- *I want higher growth* → Momentum Leaders, Adaptive Alpha, Growth Accelerators
- *I believe in India's growth story* → India Consumption Growth, Small & Midcap Smart Alpha, Dynamic Sector Rotation
- *I want stability or income* → Quality Compounders, Defensive Leaders, Dividend & Income

### 2. Named universes — `backend/app/baskets/universes.py`

Broad pools (`LARGE_CAP_CORE`, `LARGE_MID_ALPHA`, `QUALITY`, `LOW_VOL`,
`MIDCAP_LIQUID`, `HIGH_YIELD`, `CONSUMPTION`, `REITS_INVITS`) plus **nine
real sector books** (Financials, IT, Pharma, Auto, FMCG, Metals, Energy,
Infra & Capital Goods, Realty), 5–12 liquid names each — no single-stock
sector proxies. `catalog.py` builds its specs from these; Phase 2 turns
membership dynamic (liquidity / eligibility screened).

### 3. Product metadata on the model

`Basket` gains `risk_level`, `objective`, `horizon`, `investment_style`,
`how_it_works` (JSONB), `internal` (bool). Migration
`e1f2a3b4c5d6_basket_product_metadata`. `create` / `update` / `serialize`
carry them, so a cloned product keeps its identity.

### 4. API

- `GET /baskets/templates` → the **12 flagship** products, with
  `categories`, `journeys`, `risk_labels`, and per-product backtest +
  `min_funds`.
- `GET /baskets/templates?include_internal=true` → additionally returns the
  **14 back-pocket template models** under `internal_models` (kept, not
  deleted — available for internal use and for folding into Golden
  Wealth's allocation engine later).

### 5. Frontend — `frontend/src/pages/BasketsPage.tsx`

"Choose an investment product" renders the 12 grouped by investing goal.
Sort/filter works over the 12 (adds a risk-level sort); a non-default sort
or an active filter flattens to one ranked grid. Product card: category
eyebrow, coloured L1–L5 risk chip + label, objective, meta line
(horizon · style · holdings · rebalance), backtest block, expandable
"How it works", and "Min. investment ~₹X — ~N holdings".

### 6. Safe correctness fixes (from the gap analysis)

- **Minimum investment** — `unit_cost_for_spec` now sizes to the names a
  basket *actually holds* (`top_k` / hold buffer per sleeve, all members
  for static sleeves), one share each, using the average member price as
  the estimate of which names get picked. Previously it summed one share
  of the entire research universe (e.g. ₹1.56 L for a 12-stock basket with
  a 43-name pool → now ~₹53 k).
- **Benchmarks** — Adaptive Alpha & Growth Accelerators → NIFTY 500;
  Small & Midcap → NIFTY MIDCAP 150; Financials-style single-sector →
  sector benchmark (already correct).
- **Duplicate pools** — `defensive-leaders` internal pool de-duplicated
  (`_uniq(_LOW_VOL, _QUALITY)`); the flagship Defensive Leaders draws its
  two stock sleeves from separate de-duplicated universes.

## Validation

- `pytest` — full suite **711 passed, 1 skipped**. New:
  `tests/test_baskets_catalog.py` (7 tests: exactly 12 distinct products,
  every spec valid + weights sum 100, no duplicate members in any sleeve,
  every product has full metadata, journeys reference real keys, risk
  levels span 1–5, no "AI" in names).
- `ruff` clean on all touched backend files.
- Frontend `tsc -b` — only the 4 pre-existing recharts/lightweight-charts
  errors; `oxlint` clean; `vite build` passes.
- All 12 flagship backtested end-to-end (8y, costs + slippage) into
  `data/basket_catalog_backtests.json` — no errors; NIFTY 500 / NIFTY
  MIDCAP 150 benchmarks resolve.
- Migration `e1f2a3b4c5d6` applied to the dev DB.

Not done headlessly: a visual pass of the rebuilt catalog page in a
browser.

## Operating notes

- Rebuild the flagship backtests + min-investment:
  `python -m app.baskets.template_backtests catalog [years]` →
  `data/basket_catalog_backtests.json` (git-ignored).
- The old per-template file is still built by
  `python -m app.baskets.template_backtests [years]` and patched by
  `... min-funds`.

## Deferred (later phases)

- **Phase 2** — factor library (`app/baskets/factors/`): multi-horizon
  momentum, multi-MA trend + ADX, downside/beta/ATR volatility,
  decomposed quality/growth/value (live), volume; a `StockScorecard`;
  regime-adaptive factor weights. This is what makes *every* equity sleeve
  genuinely multi-factor and retires the last hardcoded lists.
- **Phase 3** — shared 5-state regime engine (`app/regime/`) used by
  baskets + scanner + seasonality.
- **Phase 4** — portfolio construction: enforce sector caps (the
  `max_sector_pct` field is currently parsed but not applied), correlation
  control, risk-contribution, score-differential replacement, tiered drift.
- **Phase 5** — universe management with metadata + eligibility screen;
  pre-scoring data-quality gate.
- **Phase 6** — factor-attribution explainability store on rebalance
  events; rolling metrics + up/down capture; full test matrix.
- **Dynamic Sector Rotation** currently concentrates in strong sectors via
  a combined sector universe; the explicit sector-score → top-3-sector
  allocation is Phase 2/4.
- **Golden Wealth** ships with the strategic allocation; the tactical
  tilt-within-ranges engine (folding in Permanent Portfolio / 60-40 /
  Risk-Parity Lite as internal models) is Phase 2.

## Confirmed constraints

- Fundamentals (quality / growth / value) feed the **live/paper signal
  only**; historical backtests renormalise them away and rank on price
  factors. Stated in each product's "how it works".
- The 14 non-flagship templates are retained, not deleted.
