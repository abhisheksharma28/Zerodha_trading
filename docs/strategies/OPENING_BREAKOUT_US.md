# Opening Breakout US (5-minute ORB + Relative Volume)

Slug: `opening-breakout-us` · Category: Breakout · Horizon: Intraday ·
Complexity: High · Long / short capable · NSE session-aware (Asia/Kolkata).

> Re-implementation of Zarattini, Barbon & Aziz, *"A Profitable Day Trading
> Strategy for the U.S. Equity Market"* (SFI Research Paper 24-98), adapted
> to the NSE cash session. **Not** guaranteed or proven profitable. The
> paper's own finding is that a plain opening-range breakout is a coin-flip
> — the edge, in US data, came entirely from restricting trades to the
> day's *Stocks in Play*. Whether that survives on NSE is an open question
> this template exists to test, not an answer it provides.

## What is copied, and what is not

The **methodology** is copied: opening-range breakout, direction locked by
the opening candle, no target, ATR-fraction stop, end-of-day exit, and —
the crucial part — a cross-sectional filter that trades only the names
whose *opening-interval* volume is far above their own recent norm.

The **numbers are not**. The paper's US filters (price > \$5, 14-day
average volume > 1,000,000 shares, 14-day ATR > \$0.50) are placeholders
here (`min_open_price`, `min_avg_daily_volume`, `min_atr`) and are labelled
as such in the parameter schema. They must be re-calibrated on NSE data
before any weight is placed on a backtest. The paper explicitly does not
assume its US results transfer to other markets.

## Concept

A large demand/supply imbalance in the first minutes of the session tends
to persist through the day. The opening candle shows the *direction* of
that imbalance; opening-interval **Relative Volume** shows whether it is
*abnormal* enough to be worth trading. Trading only the top-N highest-RVOL
names concentrates the book on the day's genuine Stocks in Play.

## Mathematical logic

For each instrument, each trading day, over bars in
`[09:15, 09:15 + opening_range_minutes)` IST:

```
OR_open, OR_high, OR_low, OR_close   (first / max / min / last)
OR_vol = Σ volume in the interval
```

Relative Volume, computed at the close of the opening interval:

```
RVOL = OR_vol(today) / mean( OR_vol over the previous rvol_lookback sessions )
```

— today's opening volume against *its own* opening-volume history, never a
full-day average. A name with fewer than `rvol_lookback` prior sessions is
not yet eligible.

Each day, once the wall clock is past the opening interval, every eligible
instrument is scored by RVOL, names below `rvol_min` are dropped, the rest
are ranked, and the top `top_n` are **armed** for the day. Eligibility
(`min_open_price`, `min_avg_daily_volume` over `rvol_lookback` sessions,
14-day `min_atr`) and the ATR itself use only closed prior sessions —
there is no look-ahead and no future-day selection.

## Direction lock

- `OR_close > OR_open` → **long only** that day.
- `OR_close < OR_open` → **short only** that day (requires `allow_short`).
- `OR_close == OR_open` → no trade.

The opposite-side breakout is never taken, even if price crosses that level.

## Entry / exit

For an armed name with no position: enter when a bar **closes** beyond the
opening-range level (`close ≥ OR_high` for a long, `close ≤ OR_low` for a
short). The paper places an intrabar *stop order* at the level; a
fill-at-close backtest engine cannot honestly model that trigger, so
"closes beyond" is used as the non-optimistic equivalent — the realised
entry on a fast bar will be worse than the opening-range level, which is
the conservative direction.

Stop: `entry − atr_stop_fraction · ATR14` for a long (mirror for a short).
It is **fixed** — never trailed, no separate rule moves it. There is **no
profit target**. Anything still open at `square_off_time` is flattened.
Nothing is ever held overnight.

## Position sizing

`sizing_method = risk_per_trade` in every preset: quantity is
`capital_allocation · risk_per_trade_pct/100 / stop_distance`, then capped
by `max_position_size_pct` of `capital_allocation`. The cap is the leverage
guard — it ensures a broker margin assumption cannot turn the modelled 1%
risk into a larger real loss.

## Multi-timeframe

`opening_range_minutes` ∈ {5, 15, 30, 60}. RVOL is always measured over the
same opening interval across the previous `rvol_lookback` sessions. **5 is
the primary configuration** — it was materially the strongest in the paper
(15/30/60 were much weaker). The others are provided for the paper's own
timeframe comparison, not as recommendations.

## Parameters

`opening_range_minutes`, `rvol_min`, `top_n`, `rvol_lookback`,
`square_off_time`, `allowed_weekdays`, `allow_short`, `min_open_price`,
`min_avg_daily_volume`, `min_atr`, `atr_period`, `atr_stop_fraction`,
`exchange`, `product`, plus common sizing parameters. Full schema:
`GET /api/v1/strategy-library/opening-breakout-us`.

Presets: `conservative` (RVOL ≥ 2, top 10, long-only, 0.5% risk),
`balanced` (RVOL ≥ 1, top 20, long+short, 1% risk), `aggressive` (looser
liquidity filters, 1% risk, 25% position cap). All are research starting
points, not recommendations.

## Assumptions

- **Intraday bars** (1-5 minute) that actually cover 09:15 through
  `square_off_time` for every instrument, delivered in time order. Daily
  bars make the strategy inert.
- A **multi-instrument universe** — the strategy is cross-sectional; with
  one instrument there is nothing to rank.
- At least `rvol_lookback + atr_period` prior sessions before the first
  tradable day.
- For a real study: a **survivorship-bias-free, point-in-time** universe
  with corporate actions handled. The synthetic-data tests in
  `backend/tests/test_opening_breakout_us_backtest.py` only prove the
  pipeline runs end to end; they say nothing about whether an edge exists.

## Backtesting checklist (before trusting any result)

1. Calibrate `min_open_price` / `min_avg_daily_volume` / `min_atr` on the
   NSE universe — do not carry the US values.
2. Reproduce the paper's structure first: base ORB (no RVOL filter) vs.
   ORB + RVOL top-N. If the base is a coin-flip and the filter adds a
   real, cost-net edge, that is the signal the paper describes.
3. Walk-forward / out-of-sample across years and market regimes.
4. Sensitivity sweeps on `opening_range_minutes`, `rvol_min`, `top_n`,
   `atr_stop_fraction`, `risk_per_trade_pct`, and the liquidity filters —
   the goal is to see whether the edge is robust, not to find the peak.
5. Always with the Indian cost model (`app.backtesting.costs`): brokerage,
   STT, exchange txn, GST, SEBI fee, stamp duty, and slippage. Breakout
   P&L is small relative to these.

See also `docs/strategies/RESEARCH_METHODOLOGY.md`.
