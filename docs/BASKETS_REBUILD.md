# Baskets rebuild — running report

Phases 1-6 + the Golden Wealth tactical engine are shipped. This file is
the chronological record; each phase section stands on its own.

---

# Phase 1 report

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

---

# Phase 2 — factor library (done)

`backend/app/baskets/factors.py` replaces the three thin single-lookback
price factors in the composite-score engine:

| Factor | Before | After |
|---|---|---|
| `momentum` | one ROC at the sleeve lookback | blend of 12-1 month, 6 month, 3 month returns (6m anchor; degrades under 1y history) |
| `trend` | distance above one MA | distance above the main MA + multi-MA structure check (px vs 50/100/200, 50>200) + 50-day MA slope |
| `low_vol` | total daily stdev | negated blend of **downside deviation** and total vol (upside vol not punished) |
| `rs` *(new)* | — | excess return vs the basket benchmark over ~126 bars |
| `volume` *(new)* | — | relative volume (21d vs 63d) signed by recent price direction |
| `dist_from_high` *(helper)* | — | distance below the rolling 52-week high |

**Plumbing:** `resolve_targets(..., market_bars=)` carries the benchmark
bar series; `rs` uses it and its weight renormalises away when absent.
`backtest.py` passes the benchmark bars; `paper.py` fetches the basket
benchmark alongside the members. `_composite_scores` also returns a
per-name `{factor: 0-100 rank}` breakdown, surfaced on
`SleeveResolution.factor_ranks` — the foundation for Phase 6
explainability.

**Per-basket factor profiles** (`catalog.py`): the alpha / growth / sector
/ consumption products now weight `rs` (and `volume` for Adaptive Alpha
and Sector Rotation). `rs` is a *confirming* weight (0.10) on the two
pure-momentum products — 126-day RS is collinear with 6-month momentum in
a price-only backtest, so a heavier weight dilutes rather than adds; it
earns its place across regimes and once the live fundamentals signal is
in the mix. Deliberately **not** tuned further to max the single 8y
backtest (the spec warns against overfitting).

**8y catalog backtest, Phase 2 vs the Phase 1 baseline** (composite-score
products only; static ETF baskets unchanged):

| Product | CAGR Δ | vs-bench Δ | Sharpe Δ |
|---|---|---|---|
| Dynamic Sector Rotation | +3.2 | +65 | +0.15 |
| Adaptive Alpha | +2.1 | +48 | +0.10 |
| Growth Accelerators | +1.5 | +28 | +0.05 |
| Small & Midcap Smart Alpha | +1.0 | +25 | +0.08 |
| India Consumption Growth | +0.9 | +12 | +0.04 |
| Momentum Leaders | +0.4 | +10 | +0.04 |
| Quality Compounders | +0.25 | +2.8 | +0.02 |
| Core Growth | −0.13 | −1.5 | −0.03 |
| Defensive Leaders | −0.44 | −5.0 | −0.03 |

The two small negatives are defensive baskets where the composite is a
minor sleeve and price-proxy quality is inherently weak — the live
fundamentals path (unchanged) is where real quality selection happens.

**Validation:** `pytest` full suite **722 passed, 1 skipped**;
`tests/test_baskets_factors.py` (10 tests) + a `resolve_targets`
market-bars / factor-ranks test. `ruff` clean.

**Still open in Phase 2's original scope:**
- ADX / beta / ATR-percentile as distinct factors (the current `trend`
  and `low_vol` cover the intent; these are refinements).
- A standalone `StockScorecard` object — `SleeveResolution.factor_ranks`
  currently serves the attribution need.
- **Regime-adaptive factor weights** — moved to Phase 3 (needs the shared
  5-state regime engine).

---

# Phase 3 — shared market regime engine (done)

`backend/app/regime/` — one 5-state classifier, no longer a per-subsystem
ad-hoc notion.

**`classify(index_closes, vix_closes=, member_closes=)` → `RegimeState`**
(`strong_bull` / `bull` / `neutral` / `caution` / `risk_off`). Signals,
each 0–1, weighted trend .32 / momentum .24 / drawdown .20 / volatility
.16 (+ breadth .08 when member series are supplied):

| Signal | From |
|---|---|
| trend | px vs SMA50 / SMA200, SMA50 vs SMA200 |
| momentum | 3-month and 6-month index return |
| drawdown | distance below the trailing 1-year high |
| volatility | 21-day realised vol vs its own 1-year range, or absolute India VIX |
| breadth | share of members above their own SMA200 |

Pure + causal — safe inside the walk-forward backtest.

**Consumers:**
- `exposure_scale(regime, floor, hard_cut)` — graduated risk-asset
  exposure: bull 100 % / neutral 85 % / caution 55 % / risk_off = the
  basket's own `risk_off_scale`. `hard_cut` (a new `RegimeGate` field)
  collapses any non-bull regime straight to the floor — set on **Small &
  Midcap Smart Alpha**, where a 1.5–2× beta basket riding pullbacks at
  partial weight blew its drawdown out by 15 pts.
- `factor_tilt(regime, weights)` — deliberately light regime-adaptive
  reweighting, **only** in the extreme states (small momentum lean in
  `strong_bull`; low-vol / quality lean in `risk_off`). An aggressive tilt
  that collapsed the momentum weight in a drawdown was found to *deepen*
  drawdowns on the aggressive equity baskets; the graduated exposure scale
  does the heavy de-risking. This is the Phase 2 "regime-adaptive weights"
  item, now unblocked.

**Wiring:** `resolve_targets` runs the engine for any basket with a
regime gate — graduated scale replaces the old binary below-200-DMA cut,
and the regime tilts each composite sleeve's factor weights.
`SleeveResolution` / rebalance events carry the 5-state label. Exposed at
`GET /market/regime` (2-min cache) and folded into the insights briefing
pulse + the Insights page.

**8y catalog backtest, Phase 3 vs Phase 2** (baskets with a regime gate):

| Product | CAGR Δ | Sharpe Δ | MaxDD Δ |
|---|---|---|---|
| Momentum Leaders | +4.1 | +0.18 | −6.1 (deeper — a return/risk trade) |
| Growth Accelerators | +1.5 | +0.12 | −1.0 |
| Adaptive Alpha | +1.1 | +0.04 | −5.2 (deeper) |
| Core Growth | +0.9 | +0.15 | −1.2 |
| Dynamic Sector Rotation | +0.9 | +0.04 | −3.6 |
| Defensive Leaders | +0.9 | +0.13 | +1.5 (shallower) |
| Small & Midcap Smart Alpha | +0.6 | +0.03 | +2.5 (shallower, via `hard_cut`) |

Every regime-gated basket improved on CAGR and Sharpe. The deeper
drawdowns on Momentum Leaders / Adaptive Alpha are a genuine return/risk
trade — Sharpe still rises, so risk-adjusted it holds. Static ETF baskets
(All Weather, Golden Wealth, Dividend, Quality, Consumption) unchanged.

**Validation:** full suite **729 passed** (10 new `test_regime.py` tests +
reworked basket regime test); ruff clean; frontend tsc/oxlint clean.

**Still open in Phase 3's scope:** the scanner and seasonality still use
their own regime notions — swapping them onto `app/regime/` is a
follow-up (the shared engine + API are in place; the migration is
mechanical but touches those subsystems' scoring).

Current live read of `GET /market/regime`: **caution** (score ~40) —
NIFTY 50 below all key averages, ~9 % off its 1-year high, but VIX calm.

---

# Phase 4 — portfolio construction (3 of 4 done)

- **Sector concentration caps** — `spec.risk.max_sector_pct` was parsed but
  never applied. `app/baskets/sectors.py` maps members to NSE sectors
  (ETF / gold / bond / cash buckets exempt); `engine._sector_cap()` trims
  any over-cap equity sector in a single pass, places the freed weight into
  under-cap sectors up to their headroom, the rest to cash. Applied after
  the single-name cap, which is then re-checked. Catalog: 30 % on Momentum
  Leaders / Adaptive Alpha / Growth Accelerators / Small & Midcap, 40 % on
  Dynamic Sector Rotation, thematic / multi-asset products uncapped.
- **Score-differential replacement** — `RuleSpec.replace_margin_pct`
  (default 0.05): a held name gets a +5-point bump on its 0-100 composite
  score when ranking, so a newcomer only displaces it once meaningfully
  better. Stacks with the `hold_k` rank buffer.
- **Tiered drift** — `plan_orders` is now `|drift| < band` → none;
  `band … 1.5×band` → partial (half-step); `≥ 1.5×band` → full. Dropped /
  new names always full. `to_weight` reports the actual post-trade weight.

8y catalog backtest across both parts: **Sharpe flat** (±0.07),
CAGR small mixed moves, drawdowns basket-specific noise. Backtest-neutral
by design — the value is fewer trades on the live path (real costs / tax).
Sector caps are a forward guardrail that rarely bound historically.

### Phase 4 part 3 — correlation control + risk contribution (done)

- **`RiskLimits.max_pair_corr`** (0 ⇒ off) + `corr_lookback`. After the
  sector cap, `engine._correlation_deconcentrate()` unions holdings whose
  pairwise daily-return correlation exceeds the threshold into clusters;
  the largest position in each cluster keeps its weight, the rest taper to
  50 %, and the freed weight moves to holdings outside any correlated
  cluster (genuine diversifiers) — leftover to cash. Shares the union-find
  / correlation machinery with `app/discovery/screen.py`.
- **`ResolveResult.risk_contribution`** — each holding's share of
  portfolio variance (`wᵢ·(Σw)ᵢ / wᵀΣw`), on every resolve, surfaced on
  the paper rebalance preview and each backtest `RebalanceSnapshot`.
- Catalog: `max_pair_corr: 0.9` on Momentum Leaders + Adaptive Alpha.
  8y backtest **exactly neutral** across all 12 products — Indian
  large/mid caps don't sustain >0.9 pairwise daily correlation on a
  rolling window, so it never fires historically. It is a live-path guard
  against the ranking bunching into near-identical names, not a return
  knob; tightening it to force a backtest effect would be curve-fitting.

---

# Phase 5 — universe management + eligibility screen (done)

- **`app/baskets/eligibility.py`** — `EligibilityGate` +
  `assess_member` / `screen_members`: a data-quality + tradeability bar
  for a sleeve's candidates (history length, staleness, internal gaps,
  penny-price floor, optional median-turnover liquidity test), with a
  per-member reason list and stats.
- **`universes.py`** — metadata for every named pool (`label`,
  selection `intent`, `curation`) via `describe()` / `catalog()`.
- **Service + API** — `universe_catalog()` and `screen_universe()` run the
  screen against live daily candles. `GET /baskets/universes` and
  `GET /baskets/universes/{name}/screen` — a read-only "what's tradeable
  right now, and why not" view that never touches the scoring path.
- The rebalance engine emits a `stale data` note when a held member's
  newest bar is > 30 d before `as_of` (visibility only, no exclusion — a
  binding gate stays opt-in through `EligibilityGate`).
- Frontend: `BasketUniversesPage` (`/baskets/universes`).

---

# Phase 6 — factor-attribution explainability (done)

- **`engine.attribution_of(res)`** — a serialisable "why these holdings"
  record: per sleeve, each name with its composite score, per-factor
  ranks, final weight and held/new status, plus the regime, dropped
  names, risk contribution and notes.
- Stored on `basket_rebalance_events.attribution` (nullable JSONB,
  migration `b4c9d2e5f6a8`); the paper rebalance / deploy write it and
  `GET /baskets/{id}/events` returns it. The backtest result carries
  `final_attribution` (the last rebalance — what a user deploying today
  actually gets).
- **New backtest metrics** — `up_capture_pct` / `down_capture_pct`
  (calendar-month buckets vs benchmark) and `rolling_12m` min / median /
  max return. Added to the catalog summary whitelist.
- Frontend: `AttributionPanel` on the basket detail page (under the
  backtest, and expandable per row in the rebalance history);
  `MetricsRow` shows the new capture / rolling stats.

---

# Golden Wealth — tactical tilt-within-bands (done)

- **`app/baskets/tactical.py`** — an allocation overlay that shifts a
  strategic multi-asset basket's sleeve weights inside hard per-sleeve
  bands each rebalance. Models: `strategic` (identity), `trend_tilt`
  (default — lean toward the asset with the stronger 200-DMA + 6-month
  momentum; never lean growth up in a `risk_off` regime), `risk_parity_lite`,
  `permanent_portfolio`, `sixty_forty`. A `max_step_pct` cap keeps every
  sleeve within N points of strategic per rebalance.
- **`spec.TacticalSpec`** — `model` + `max_step_pct` + per-sleeve
  `[strategic, floor, ceiling]` bands, validated so band strategics match
  sleeve weights, every sleeve is covered, and floors/ceilings can
  bracket 100. `resolve_targets` applies it before the sleeve loop;
  `SleeveResolution.target_pct` carries the tilted weight; backtest
  warm-up bumped to 210 bars when a tilt is active.
- Golden Wealth switched to `trend_tilt` (equity 35-60 / midcap 5-20 /
  bonds 15-30 / gold 10-30 / liquid 5-20, 8-pt step). 8y backtest:
  **CAGR 12.03 → 13.02, Sharpe 1.407 → 1.422, MaxDD -18.67 → -18.73,
  turnover 24.9 → 19.2** — a modest genuine gain with *lower* churn
  (rebalancing to a slowly-moving target beats snapping to fixed weights
  quarterly).

---

## Deferred / assessed

- **Phase 3 follow-up (migrate scanner + seasonality regime onto the
  shared engine) — not worth doing.** There is no real duplication: the
  scanner has no index-level regime concept (only per-stock trend
  factors), `app/seasonality/regime.py` is a monthly point-in-time
  2×3 (trend × vol) classifier for the research pipeline, and
  `app/adaptive_options/regime.py` is an IV-rank/term-structure options
  classifier. Different time semantics and purposes; forcing one
  abstraction would lose meaning for no gain. They already share the live
  read via `/market/regime` and the insights briefing.
- **Dynamic Sector Rotation** still concentrates via a combined sector
  universe; an explicit sector-score → top-3-sector allocation layer
  remains a possible enhancement.
- **Discovery P1b** — fill the full ETF universe + USD/INR (needs
  `TWELVEDATA_API_KEY` or more MCP CSV fetches into
  `data/discovery_seed/`).

## Confirmed constraints

- Fundamentals (quality / growth / value) feed the **live/paper signal
  only**; historical backtests renormalise them away and rank on price
  factors. Stated in each product's "how it works".
- The 14 non-flagship templates are retained, not deleted.
