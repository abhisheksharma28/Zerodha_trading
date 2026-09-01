# Pairs Trading / Statistical Arbitrage

Slug: `pairs-trading` · Category: Statistical Arbitrage · Horizon:
Market-neutral · Complexity: High · Long / short / market-neutral · exactly
two instruments.

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable.
> Statistical relationships between two assets can and do break down
> permanently.

## Concept

Two economically-linked instruments (e.g. two large private-sector banks)
tend to move together, so the *spread* between them is more mean-reverting
than either leg. The strategy trades deviations of the spread's Z-score,
long one leg and short the other, sized to be roughly value-neutral, and
unwinds as the spread reverts.

## Mathematical logic

With legs A and B and hedge ratio β:

```
β_t     = OLS slope of log(A) on log(B) over regression_window   (rolling_ols)
        | frozen first estimate                                   (static)
        | 1                                                       (price_ratio)
spread_t = log(A_t) - β_t · log(B_t)          (or A_t / B_t for price_ratio)
mean_t   = SMA(spread, lookback)
std_t    = sample stdev(spread, lookback)
Z_t      = (spread_t - mean_t) / std_t
```

Optional cointegration gate: an Augmented Dickey-Fuller t-statistic on the
last `cointegration_lookback` spread values; trade only while it is below
`adf_threshold` (more negative = stricter). This is a hand-rolled AR(1) OLS
t-stat, not statsmodels — a rough screen, not a formal test.

## Entry / exit

**Short-spread** (sell A, buy B) when `Z_t ≥ entry_zscore`.
**Long-spread** (buy A, sell B) when `Z_t ≤ -entry_zscore`.
Exit when `Z_t` reverts to `±exit_zscore`, runs past `±stop_zscore` against
the position (relationship broke — get out), or after `max_holding_bars`.
The strategy only acts on bars where both legs have an equal number of
observations (time-aligned).

## Position sizing

`qty_A = per_leg_capital / P_A` where `per_leg_capital = min(capital/2,
capital · max_position_size_pct/100)`. For log-spread methods the B leg is
**value-neutral**: `qty_B = round(qty_A · P_A / P_B)`. For `price_ratio`,
`qty_B = per_leg_capital / P_B`.

## Risk

The `stop_zscore` is essential — it is the only defence against a structural
break where the spread diverges and never comes back. `max_holding_period`
bounds exposure time. Market-neutrality reduces but does not remove risk
(both legs can move against you; the short leg has borrow cost, not
modelled).

## Parameters

`lookback`, `regression_window`, `hedge_ratio_method`, `entry_zscore`,
`exit_zscore`, `stop_zscore`, `max_holding_bars`, `require_cointegration`,
`cointegration_lookback`, `adf_threshold`, `min_spread_std`. Full schema:
`GET /api/v1/strategy-library/pairs-trading`.

## Assumptions

- Exactly two instruments, time-aligned bars, both prices positive.
- Both legs are cheaply shortable and tradeable in the sizes produced.
- The historical relationship persists over the holding period.
- Automatic pair discovery is **not** implemented — pairs are chosen
  manually (pass the two instruments as the universe).

## Known weaknesses

- **Structural break**: the dominant failure — a merger, regulation change,
  or business-model divergence permanently changes the ratio.
- **Hedge-ratio instability**: a noisy rolling β makes the spread and its
  Z-score unreliable; `static` is more stable but goes stale.
- **Both-legs-adverse**: a market shock can move both legs against the
  position before the stop.
- **Cointegration illusion**: short windows produce spurious ADF passes.

## Transaction-cost considerations

Two legs per entry and two per exit — four order-sides per round trip — so
cost per trade is roughly double a single-leg strategy. The captured spread
is often small; sweep `slippage_bps` and compare `net_pnl`/`gross_pnl`
carefully. `NRML` product; STT/stamp/exchange charges apply to each leg.

## Look-ahead-bias considerations

β, the spread series, its mean/std/Z, and the ADF statistic for bar *t* all
use data up to and including *t* only, and both legs must be aligned to the
same count of bars. No future observation enters the hedge ratio or the
signal. Covered by explicit look-ahead and cointegration-gate tests.

## Survivorship-bias considerations

Choosing the pair with hindsight ("HDFCBANK/ICICIBANK worked") is itself a
survivorship decision. Ideally form the pair from a prior, out-of-sample
window and trade it forward. Document how the pair was selected.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Additionally: form the pair on a training
window and test the *same* pair and β process out-of-sample; monitor rolling
correlation and re-run the cointegration screen through the test period; be
ready to retire the pair when it stops passing.
