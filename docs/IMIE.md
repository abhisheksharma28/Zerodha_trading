# Intraday Move Intelligence Engine (IMIE)

A quantitative intraday analysis subsystem that ranks NSE instruments by
the probability of a significant intraday move developing, and classifies
where each one sits in the compression → pressure → breakout → expansion
state machine.

**It does not predict the future.** Every number is an empirical
probability, a percentile, or a level derived from historical
distributions, with the working shown. Where the data does not support a
feature it is disabled and flagged, never faked.

---

## Integration

Isolated package `backend/app/imie/`. It **reads** the existing plumbing
(Kite client, `app/live` tick feed + `MARKET_STATE`, `app/orderflow`
capabilities + estimated delta, `app/strategies/indicators`,
`nse_universe` sector map, `instruments` master) and **writes only** its
own tables. It touches nothing in strategies, backtesting, the scanner,
the screener or execution. A new "Intraday Radar" entry under the
frontend **System** menu; routes `/imie` and `/imie/:symbol`.

---

## Data sources & limits (honest assessment)

| Need | Source | Status |
|---|---|---|
| 1-minute OHLCV, intraday | Kite historical (`get_historical_candles`, `minute`), ~55d/req, paged | **TRUE** |
| Live LTP / cum. volume / 5-level depth / OI | Kite ticker, ~1 snapshot/s (`app/live`) | **TRUE (1 Hz)** |
| Session VWAP, volume profile (1m) | derived from 1m bars (`app/orderflow`) | **TRUE / LIMITED** |
| Time-of-day volume baseline | built from trailing 1m sessions | **TRUE** |
| Relative strength vs index / sector | index + sector-index quotes | **TRUE** |
| Futures / options OI, PCR, IV | Kite quote `oi`, `option_chain`, BS-IV | **TRUE (live), LIMITED (no IV history yet)** |
| Estimated delta / CVD | quote-rule signed per snapshot (`app/orderflow`) | **ESTIMATED** |
| Absorption | high-vol + low-range 1m bars + estimated-delta sign | **ESTIMATED** |
| Trade-by-trade prints, aggressor flag, full L2, historical ticks/depth | — | **UNSUPPORTED** — true footprint / true delta / spoof detection are not computable and are not attempted |

The engine degrades per instrument: no broker session → `available:false`;
thin history → lower `confidence`; no F&O → derivatives score omitted.

---

## Phases

**Phase 1 (this change).** Data adapters; 1-minute scan loop; feature
modules — volatility compression, time-adjusted relative volume, VWAP,
market structure, relative strength, estimated absorption; the 8-state
machine; configurable composite Opportunity Score with per-factor
explainability; a lite empirical move-probability / direction / magnitude
from each instrument's own trailing same-state distribution;
quantitative trade-setup levels; signal + state-transition persistence
(reproducible snapshots); the Radar dashboard + Signal Detail page;
editable config (weights, thresholds, opening-range, universe, move
thresholds).

**Phase 2.** Cross-instrument historical-similarity engine (nearest
neighbour over the feature vector, strict no-lookahead); intraday
backtester with full Indian charges + slippage; walk-forward validation;
baseline strategies (ORB / VWAP-cross / breakout / random) to beat;
LightGBM / logistic move + direction models trained on the persisted
feature snapshots.

**Phase 3.** Futures OI build-up/unwind classification, option OI
concentration & PCR/IV-percentile (once enough IV history is stored),
richer estimated order-flow.

**Phase 4.** Automated retraining, live calibration monitoring, weight
optimisation, per-regime / per-time-of-day performance breakdown.

---

## Composite score

`opportunity_score` (0–100) = weighted mean of the 0–100 factor scores.
Default weights (editable in `ImieConfig`, never hard-coded as the only
source): compression 25, relative volume 20, structure 20, VWAP 15,
relative strength 10, derivatives 10 — renormalised over the factors that
have data. Bands: <30 low · 30–50 watch · 50–70 setup · 70–85 high · 85+
exceptional.

## Run

Backend loop starts from the app lifespan when `imie_enabled` (default
true), market-hours gated. `POST /imie/scan` triggers a cycle now.
Frontend: System → Intraday Radar.
