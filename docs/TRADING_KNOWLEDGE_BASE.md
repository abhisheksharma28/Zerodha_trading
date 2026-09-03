# Trading Knowledge Base

Distilled, actionable rules from the reference material the platform owner has
supplied. This is the **specification and backlog for the Trading Ideas engine**
(`backend/app/market_scanner/`), not something the running service parses.

**How the tool uses this at runtime:** the engine acts on what is *coded* into
`app/market_scanner/`, and every weight / threshold / on-off switch that code
uses is read from **`app/market_scanner/knowledge.py`**, which deep-merges an
optional **`knowledge.yaml`** override at import (`GET /market-scanner/knowledge`
to inspect, `POST /market-scanner/knowledge/reload` to re-read). So the rules
below can be re-tuned live by editing the YAML — no code change. Each entry is
tagged with its status:

| Tag | Meaning |
|---|---|
| ✅ `<file>` | implemented; the scorer already uses it |
| 🔜 candidate | worth implementing next; not wired yet |
| 📖 principle | informs design / risk rules, not a computed signal |

The strict score (`signals._quality_score`, grades A ≥ 74 / B ≥ 58 / C, ceiling
90) blends weighted factor groups: `trend`, `momentum`, `structure`, `location`,
`candlestick`, `chart_pattern`, `volume`, `fundamental`, `context`, `news`.

---

## 1. Source material

| Source | What it gave us |
|---|---|
| Candlestick pattern image (16 patterns) | the base candlestick spec |
| "Identifying Chart Patterns" — Kirkpatrick / Fidelity | multi-swing patterns + measured-move targets + the "not active until breakout" rule |
| Zerodha Varsity Module 2 — Technical Analysis | Marubozu, Spinning Top, S&R, the candle-length "trade trap" |
| NSE "Technical Analysis" workbook | confirmation of the above + MFI, Williams %R, Fibonacci, gap taxonomy, Elliott |
| "Trading for a Living" — Dr Alexander Elder | Triple Screen, Elder-ray, Force Index, the 2% / 6% money-management rules |
| "The Intelligent Investor" — Benjamin Graham | the defensive-investor stock screen (P/E, P/B, blended 22.5, current ratio) |
| "Alchemy of Finance" — George Soros (scanned, no text layer) | reflexivity / boom-bust — used from the known thesis |
| "Synergizing quantitative finance…" (Mengshetti et al., 2024) | the Weapon Candle strategy (EMA9 reclaim + MACD + VWAP + RSI) |
| "Quantitative Trading Strategy… NEPSE" (Poudel & Paudel, 2025) | Z-score + RSI + MA240 regime-filtered mean reversion |
| Karmakar & Chakraborty (2000) | Indian monthly / turn-of-month calendar effect |
| Dr Reshampal Kaur material | MACD-gated 1% averaging grid |

---

## 2. Candlestick patterns — ✅ `candles.py`

Each detector needs the prevailing short-term trend as context (`_short_trend`),
**except Marubozu** which is valid in any trend. Weights in
`signals._CANDLE_WEIGHT`.

| Pattern | Definition (body/wick ratios off one to three closed bars) | Direction | Notes |
|---|---|---|---|
| Hammer / Hanging Man | body ≤ 0.35·range, lower wick ≥ 2·body, upper wick ≤ body | bull in a downtrend / bear in an uptrend | |
| Shooting Star | body ≤ 0.35·range, upper wick ≥ 2·body, lower wick ≤ body, uptrend | bearish | |
| Bullish / Bearish Engulfing | current body covers the prior body, opposite colour, ≥ 1.05× | reversal of the trend | |
| Piercing / Dark Cloud Cover | 2-bar; second closes past the prior body midpoint (not through it) | reversal | |
| Bullish / Bearish Harami | large body then a small opposite body wholly inside it | reversal | |
| Doji reversal | prior bar a doji (body/range ≤ 0.1), current bar closes beyond its extreme | reversal | |
| Morning / Evening Star | 3-bar; small middle body, third closes past the first body midpoint | reversal | |
| **Bullish / Bearish Marubozu** | body/range ≥ 0.9, both wicks ≤ 0.08·range; **1% ≤ range ≤ 10% of price** ("trade trap": skip subdued or over-extended candles) | strong momentum, any trend; **entry = close, stop = opposite extreme** | Varsity Ch. 5 |
| **Spinning Top** | body/range ≤ 0.3, upper & lower wicks each ≥ 0.25·range and within 60% of each other | indecision — soft ±4 nudge read from the trend ("calm before the storm") | Varsity Ch. 6 |

Varsity rules that shape the scorer: *buy strength / sell weakness*, *verify and
quantify* (a 0.1–0.5% wick is still a Marubozu), *look for prior trend*, and the
risk-averse entry is the **confirmation day** (next bar in the signal direction).

---

## 3. Multi-swing chart patterns — ✅ `chart_patterns.py`

Read off `structure.swings` (the alternating fractal-pivot sequence). **A pattern
carries signal weight only once its breakout has `status == "confirmed"`**; a
"forming" pattern is ignored (Kirkpatrick). Every pattern has a measured-move
target = pattern height projected from the breakout. Weights in
`signals._CHART_WEIGHT`.

| Pattern | Skeleton / rule | Target |
|---|---|---|
| Double Top / Bottom | H·L·H (or L·H·L) with the two extremes ≈ equal; confirm on a close past the middle pivot | height projected from the breakout |
| Triple Top / Bottom | three ≈ equal extremes separated by two counter-pivots | highest-to-lowest height projected |
| Head & Shoulders (+ inverse) | H·L·H·L·H with a higher centre and ≈ level shoulders; neckline = the two inner pivots; confirm on a neckline close | (head − neckline) projected from neckline — "one of the lowest failure rates" |
| Ascending Triangle | flat highs, rising lows; break the flat top | range height added to the top |
| Descending Triangle | flat lows, falling highs; break the flat bottom | range height subtracted from the bottom |
| Symmetrical Triangle | lower highs + higher lows; direction from the actual break only | height projected from the break |
| Rectangle | flat highs and flat lows, height > 2% of price; break either edge | height projected |

🔜 candidate: **Flag / Pennant** (flag-pole height projected), **Wedge**
(rising/falling), **Cup & Handle**, **gap taxonomy** (breakaway / runaway-measuring
/ exhaustion; "explosion gap pivot" entry), **NR4 / inside-bar** volatility
contraction.

Confirmation-filter menu (apply to any breakout): intrabar / multiple closes /
time / percent-or-point / money. False breakout vs failed breakout (trap) →
stop-and-reverse. Retracement entries: throwback (after an up-break), pullback
(after a down-break).

---

## 4. Price structure, S&R, Dow theory — ✅ `structure.py`

Fractal swing pivots → BOS / CHoCH, fair-value gaps, order blocks, liquidity
sweeps, trend = higher-highs-and-lows / lower-highs-and-lows / range. Dow theory
(tide / wave / ripple; trend persists until a clear reversal; volume confirms) is
the model `structure.py` implements. Broken support becomes resistance and vice
versa.

🔜 candidate: **Fibonacci retracement zones** (23.6 / 38.2 / 50 / 61.8%) as
extra S&R confluence in `structure.py`.

---

## 5. Indicators

| Indicator | Status | Rule as used |
|---|---|---|
| EMA 20/50/200 stack, 50/200 golden/death cross | ✅ `features.py` → `trend` group | 20>50>200 = BULL; cross age decays the weight |
| RSI(14) + zones | ✅ `features.py` → `momentum` | bullish 45–68 long / 32–55 short; extended ≥ 74 / ≤ 26 penalised |
| MACD histogram state | ✅ `features.py` → `momentum` | rising/falling × pos/neg |
| ADX(14) | ✅ `signals._quality_score` `trend` sub-score | < 16 → "chop" hard cap unless the setup is a reversal |
| ATR(14) | ✅ everywhere | stop = 1.5·ATR (max 3·ATR), targets, risk % |
| VWAP + bands | ✅ `features.py` → `location` | above/below session VWAP |
| Bollinger %B | ✅ `features.py` | position in the band |
| **Elder Force Index** = `Vol·(close − prevClose)`, 13-EMA, price-normalised | ✅ `features.py` `force_index_13` → `signals._volume_factors` | 13-EMA > 0 → bulls control (+4, +6 if rising); < 0 → bears (−4, −6 if falling); flat near zero → trendless, no signal |
| **Elder-ray** Bull Power = `High − 13EMA`, Bear Power = `Low − 13EMA` | 🔜 candidate | best signals are **divergences** (price new low, Bear Power shallower) confirmed by the 13-EMA turning |
| Money Flow Index (volume-weighted RSI) | 🔜 candidate | divergence vs price = reversal warning |
| Stochastic / Williams %R | 🔜 candidate (RSI already covers the zone read) | oversold in an uptrend = buy-the-dip timing |

---

## 6. Multi-timeframe method — Elder's Triple Screen — 📖 (the scanner's design)

1. **Screen 1 — market tide:** the long-term chart (≈ 5× the trading TF). Trade
   only *with* its trend. Elder's original tool = the slope of the **weekly
   MACD-histogram** (last two bars); best buys when it turns up *below* the
   zero line.
2. **Screen 2 — market wave:** an oscillator on the trading TF, used *against*
   the tide — buy dips in an uptrend, sell rallies in a downtrend (e.g. 2-day
   Force Index turning negative, Stochastic oversold).
3. **Screen 3 — entry:** a trailing buy-stop just above the prior bar's high
   (opening-range-breakout style); protective stop at the two-day range extreme.

The scanner already embodies this: **daily trend gate → 15-minute
structure/oscillator for entry timing → concrete entry trigger + ATR/structure
stop.** 🔜 candidate: add the weekly-MACD-slope as an explicit higher-TF gate.

---

## 7. Fundamentals — Graham's defensive-investor screen — ✅ `fundamentals.py`

From *The Intelligent Investor* ch. 14. Applied to SWING equity ideas only, as
`fundamental` factors.

| Criterion | Threshold | Status |
|---|---|---|
| Adequate size | market cap large-cap (universe already tiers by liquidity) | 📖 (universe) |
| Strong balance sheet | current ratio ≥ 2 **and** long-term debt ≤ working capital (proxy: D/E ≤ 1) | ✅ flag `graham-strong balance sheet` (+3) |
| Earnings stability | positive EPS each of the last 10 years (proxy: not "earnings contracting") | ✅ existing flag |
| Dividend record | uninterrupted 20 years (proxy: pays a dividend) | 🔜 candidate |
| Earnings growth | ≥ 33% over 10 years (≥ 50% is better) | ✅ growth sub-score |
| Moderate P/E | ≤ 15× three-year average earnings | ✅ valuation sub-score |
| Moderate P/B | ≤ 1.5× book |
| **Blended multiplier** | **P/E × P/B ≤ 22.5** | ✅ flag `graham value (P/E x P/B <= 22.5)` (+5); `≥ 45` → `graham-expensive` (−4) |

"Margin of safety" and "Mr. Market" (price is a servant, not a guide) are the
governing principles behind the whole fundamental overlay.

---

## 8. Calendar / seasonality — ✅ `context.py` `calendar_bias`

Karmakar & Chakraborty (2000): Indian **turn-of-month effect** (last 2 + first 3
trading days carry 2.5–4× the mean return) and a firmer **first half of the
month**. Long-favouring near the turn (+0.7) and in the first half (+0.35); mild
negative deep in the second half (−0.3).

---

## 9. Strategy templates derived from the material — `app/strategies/library/`

| Template | Source | Status |
|---|---|---|
| `weapon-candle` — EMA9 reclaim + MACD confirmation, break of the signal bar | Mengshetti et al. 2024 | ✅ implemented |
| `macd-grid` — MACD-line-above-signal filter + 1% averaging grid, flatten on MACD cross-down | Dr Reshampal Kaur | ✅ implemented — **note:** this deliberately averages *into* weakness, which Elder / Vince explicitly warn against (see §10); labelled with that risk |
| `zscore-regime-mr` — Z-Score + RSI oversold entry, long MA regime filter, ATR stop + take-profit + cool-down | Poudel & Paudel 2025 | ✅ implemented |
| `triple-screen` — long-MA-slope "tide" + RSI pullback + prior-bar-break trigger | Elder, *Trading for a Living* | ✅ implemented |
| `elder-force-index` — 13-EMA price trend + 2-EMA Force Index dip entry, exit on trend / FI centreline flip | Elder, *Trading for a Living* | ✅ implemented |

### 9a. Well-known "proved" families added to the catalog

Widely documented, decades-old strategies exposed as fully parameterised templates (no
hard-coded numbers) so the algo runs and backtests them alongside the rest. Each carries
its own `warning` — none is guaranteed profitable, and on Indian large-caps over a fixed
multi-year window a naive version often trails an equal-weight buy-and-hold (the catalog
now shows that benchmark next to every result).

| Template | Source | Status |
|---|---|---|
| `supertrend` — ATR-band trend follower; long on an up-flip, the line is the trailing stop; optional confirm-bars, regime MA, ATR take-profit | Olivier Seban; ubiquitous on Indian retail platforms | ✅ implemented |
| `golden-cross` — 50/200 MA regime (SMA or EMA), long while fast > slow, ATR stop | classic Dow-era trend filter | ✅ implemented |
| `rsi2-reversion` — RSI(2) washout buy in a long-MA uptrend, exit on the snap-back / fast-MA / time / ATR stop | Connors & Alvarez, *Short Term Trading Strategies That Work* | ✅ implemented |
| `bollinger-reversion` — fade a close below the lower band (%B) while the longer trend is up, cover at the mean | Bollinger, *Bollinger on Bollinger Bands* | ✅ implemented |
| `fiftytwo-week-high` — long while price sits within a band of its trailing 252-day high with positive momentum; exit a set % below the running high | George & Hwang 2004, *The 52-Week High and Momentum Investing* (JF) | ✅ implemented |
| `dual-momentum` — monthly: hold the top-N of a basket by trailing return, but only names whose own trailing return is positive (absolute-momentum gate) | Antonacci, *Dual Momentum Investing* | ✅ implemented |

> Buffer-sizing gotcha (for future templates): `TemplateStrategy._compute_buffer_maxlen`
> only counts a param toward the bar-buffer length if its **name** contains `lookback`,
> `period`, `window` or `regression`. A long regime-MA param called anything else
> (`regime_ma`, `trend_ma`, `slow`, …) silently gets the 250-bar default buffer and the
> entry never fires. Name long-lookback params accordingly, or cap their `max` at ~250.

### 9b. Per-strategy dynamic test plans — `app/leaderboard/config.py::TEST_PLANS`

The leaderboard no longer tests every strategy on one fixed basket. Each strategy
has a `TestPlan` naming a **market screen** (`app/leaderboard/universe.py`) that
picks the names that actually fit that strategy, plus timeframe / window / preset.
The screen runs at refresh time over a shared daily candle pool
(`app/leaderboard/market_pool.py` — the liquid NSE cash list + sector/broad
indices), records a plain-English rationale, and freezes its choice to
`data/leaderboard_universe/<slug>.json` so robustness and tuning reuse the exact
same names. The `config_hash` covers the plan, not the day's list.

| Screen | Picks | Used by |
|---|---|---|
| `mean_reverting` | most negative 1-day return autocorrelation + Hurst < 0.5 | RSI-2, Bollinger fade, z-score MR, mean-reversion |
| `trend_persistent` | highest blend of median ADX(14) and Hurst > 0.5 | Supertrend, Donchian, golden cross, 52-week-high, MACD-grid, Elder family |
| `broad_cross_section` | the liquid cross-section itself (nothing pre-sorted) | cross-sectional momentum, multi-factor, dual momentum, Chinese Transformer, regime switchers |
| `low_volatility` / `high_volatility` | realised-vol deciles | low-vol anomaly / intraday breakout |
| `sector_index_basket` | the NSE sector indices | sector momentum rotation |
| `cointegrated_pair` | the pair with the most stationary log-spread (hand-rolled Engle-Granger ADF, half-life gate, `t < −3`) among the 30 most liquid | pairs trading |

Windows widened to **5 years** for daily strategies (the old 3y was one bull run —
equal-weight NIFTY 200 did +62% over it, so every strategy "lost"). Screens are
causal in signal but select on full-window *character*; that plus the
already-disclosed survivorship bias (NSE has no point-in-time membership) is
surfaced on every result.

**New strategies (2026-09):**

| Template | Source | Screen |
|---|---|---|
| `low-volatility-anomaly` — hold the lowest-realised-vol names equal-weight, monthly, optional trend filter | Haugen & Baker; Baker–Bradley–Wurgler; Blitz–van Vliet | `low_volatility` |
| `sector-momentum-rotation` — hold the top-N NSE sector indices by 6-month return, monthly, absolute-momentum gate | Faber, *Relative Strength Strategies for Investing* | `sector_index_basket` |
| `pairs-trading` (promoted out of `UNSUITED`) — spread z-score reversion; the tool now screens for the pair | Gatev–Goetzmann–Rouwenhorst | `cointegrated_pair` |

**New strategies (2026-09, Phase B):**

| Template | Source | Screen |
|---|---|---|
| `ttm-squeeze` — Bollinger contracting inside Keltner ("squeeze on"), enter on the release bar in the direction of momentum | Carter, *Mastering the Trade* | `trend_persistent` |
| `turn-of-month` — hold the index long only from ~day 26 through ~day 4 of the next month | Ariel 1987; Lakonishok–Smidt 1988; McConnell–Xu 2008 | `index_proxy` (NIFTY 50) |
| `rs-line-high` — long when the relative-strength line (price / index) makes a new high and price is near its own high | IBD / Minervini | `leaders_with_benchmark` (liquid names + NIFTY 50) |
| `vwap-reversion` — intraday fade of extension from the running session VWAP, flat by the close | desk-standard | `high_volatility` (screened on daily, backtested on 5m) |

`opening-breakout-us` moved to `UNSUITED` — it models US-market-open microstructure
(RVOL "stocks in play", session mechanics) and is a 1,900-line template that
CPU-hung the refresh twice on NSE 5-minute data; `opening-range-breakout` is the
NSE version.

**New strategies (2026-09, Phase C):**

| Template | Source | Screen |
|---|---|---|
| `volatility-contraction-breakout` — multi-week tight base + compressing vol, buy the break above the range if not already extended; stop on the base, target = R multiple | Minervini VCP; Darvas; Wyckoff accumulation | `consolidation_prone` (names that historically build tight bases) |
| `seasonal-sector-rotation` — each month hold the sectors with the strongest *historical record for that calendar month* (mean/median return + hit rate), built causally from history so far | calendar-seasonality literature | `sector_index_basket` (indices-only pool, 10y) |
| `seasonal-sector-stock-rotation` — same seasonal engine, but holds the individual **stocks** in the month's favoured sectors (sector = the sector index each stock correlates with most over `corr_window`) that pass a technical gate (ROC > 0, close > SMA, RSI ≤ max); a *current* fundamentals quality gate is applied upstream in the screen | seasonality + Minervini-style trend/quality filters | `seasonal_sector_stock_leaders` (liquid stocks clearing a yfinance quality gate + the sector indices, 10y) |

Seasonality helper: `app/strategies/seasonality.py::monthly_sector_stats` /
`best_sectors_for_month` / `report` (lives under `app.strategies`, not
`app.leaderboard`, to avoid a circular import). `GET /leaderboard/seasonality`
(`service.sector_seasonality`) returns the full month-by-month sector table over
~10 years — the standalone "which sector is strong in which month" insight.
`TestPlan.pool_scope="indices"` skips the ~400 equity pulls for sector/index
strategies.

**Fundamentals in a backtest:** no point-in-time fundamentals exist (yfinance
`get_key_metrics` is present-day). So `seasonal_sector_stock_leaders` applies the
quality gate *once, at screen time, with current data* — a mild look-ahead on
which companies are "quality", disclosed as a caveat on every result. Screens
that need `settings` (for a provider fetch) declare a `settings` kwarg;
`universe.run_screen` forwards it by signature inspection.

> Refresh operational note: run the canonical suite as a **standalone process**
> (`SessionLocal()` + `service.refresh_all`), not through the uvicorn worker — a
> synchronous `POST /leaderboard/refresh` blocks the single web worker for the
> whole run and `--reload` can't restart it, wedging the server.

---

## 10. Risk & money management — 📖 (rules baked into the paper algo + scorer)

From *Trading for a Living* ch. 47–48 and Vince:

- **2% rule** — never risk more than 2% of equity on a single trade (incl. costs);
  professionals use 1–1.5%. If the logical stop would risk more than 2%, **skip
  the trade**. → the paper auto-trader's `pct_per_trade` default is 2%; the
  scanner's `max_risk_pct` gates enforce a sane stop distance.
- **6% rule** — stop trading for the month once cumulative losses hit ~6%. → the
  auto-trader's `daily_loss_stop_pct` (default 5%) is the daily analogue; it
  halts new auto trades for the day.
- **Never average down. Never meet a margin call. If you must lighten up,
  liquidate the worst position. The first mistake is the cheapest.**
- **Pyramiding** is allowed only when the existing position is at break-even or
  better and the added risk is still ≤ 2%.
- **Stop placement:** long → below the latest minor support; short → above the
  latest minor resistance; Triple Screen → the two-day range extreme.
- **Break-even stop** once price moves more than one average daily range in your
  favour. **Protect-profit:** trail so ≤ 2% of *growing* equity is exposed, or
  the "50% rule" (stop halfway between entry and the best price).
- Martingale / optimal-`f` over-betting guarantees ruin; **when in doubt, risk
  less.** A small account should hold one position and watch it closely.
- Keep a before/after trade journal — the platform's Scanner Log Book is this.

---

## 11. Reflexivity — George Soros — ✅ small factor in `signals.py`

Prices are not a passive read of fundamentals: participants' biased views move
prices, and prices feed back into the fundamentals (financing, sentiment,
collateral). Trends are **self-reinforcing** until they run to a far-from-
equilibrium extreme, then reverse — the bust is faster than the boom.

Engine use (`_reflexivity_factor`, small weight): a trend-following idea gets a
mild boost when price, fundamentals and headlines all point the same way, and a
mild penalty once price is > 30% from its 200-EMA (late-stage / "moment of
truth").

---

## 12. Options / greeks / PCR — ✅ `options_overlay.py`

For F&O underlyings the OPTION idea attaches a defined-risk vertical spread built
from **real Kite quotes** (never synthesised), with `pop` (lognormal), IV, net
debit, breakeven, and a **chain pulse**: OI-PCR (≥ 1.3 contrarian bullish /
≤ 0.7 call-writers capping), a crude max-pain, ATM IV and the 1-expiry expected
move. Adaptive Options' fuller greeks/PCR/regime engine is folded in
backend-only; it is not a nav destination.

---

## 13. Candidate backlog (not yet wired)

- Elder-ray Bull/Bear Power + divergence detection
- Money Flow Index + MFI/price divergence
- Fibonacci retracement zones in `structure.py`
- Flag / Pennant / Wedge / Cup-and-Handle chart patterns
- Gap taxonomy (breakaway / measuring / exhaustion) + explosion-gap-pivot entry
- NR4 / inside-bar volatility-contraction breakout
- Weekly-MACD-slope higher-timeframe gate (Triple Screen screen 1)
- `zscore-ma240` regime mean-reversion template
- Graham "20-year dividend record" flag once the data path exposes dividend history
