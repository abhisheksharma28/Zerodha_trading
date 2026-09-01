# Mean Reversion

Slug: `mean-reversion` · Category: Mean Reversion · Horizon: Swing / Intraday ·
Complexity: Medium · Long / short capable.

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable. Mean
> reversion can experience severe losses during persistent trends.

## Concept

Over short horizons, prices that move unusually far from a rolling average
tend to snap back (short-term reversal; e.g. Lehmann 1990). The strategy
fades stretched moves and exits as price reverts, with optional confirmation
filters and a market-regime guard.

## Mathematical logic

```
mean_t = SMA(close, lookback)
std_t  = sample stdev(close, lookback)
Z_t    = (close_t - mean_t) / std_t
```

**Long** when `Z_t ≤ -entry_zscore` and every enabled filter agrees and the
regime guard permits longs. **Short** when `Z_t ≥ +entry_zscore` (if
`allow_short`). Optional filters: RSI below `rsi_oversold` (long) / above
`rsi_overbought` (short); close below the lower / above the upper Bollinger
band; close below session VWAP (intraday longs); bar volume ≥ `min_volume`;
20-bar realized volatility ≤ `max_volatility_pct`.

## Entry / exit

Exit a long when `Z_t ≥ exit_zscore` (default 0, i.e. back to the mean), when
`Z_t ≤ -stop_zscore` (the move kept going — abandon), or after
`max_holding_bars`. Shorts mirror.

## Position sizing

Common `sizing_method`. For `risk_per_trade`, the stop distance is
approximated as `stop_zscore · std_t`.

## Risk

The Z-score stop is the core control: it caps the loss when a name trends
against the position instead of reverting. The **market-regime filter**
(`regime_filter_enabled`, `regime_benchmark`) disables long entries while the
benchmark is below its trend SMA — this is what stops the strategy buying
every falling knife in a market-wide selloff. `max_holding_bars` bounds
time-in-trade.

## Parameters

`lookback`, `entry_zscore`, `exit_zscore`, `stop_zscore`, `allow_short`,
`use_rsi_filter` / `rsi_period` / `rsi_oversold` / `rsi_overbought`,
`use_bollinger_filter` / `bollinger_std`, `use_vwap_filter`, `min_volume`,
`max_volatility_pct`, `max_holding_bars`, plus common sizing/risk/regime
parameters. Full schema: `GET /api/v1/strategy-library/mean-reversion`.

## Assumptions

- One instrument per instance; benchmark bars in the stream if the regime
  filter is on.
- VWAP filter assumes intraday bars (it resets each calendar day).
- Fills at the signal bar's close plus slippage.

## Known weaknesses

- **Trend risk**: the classic failure mode — a cheap asset gets cheaper and
  never reverts. The Z-stop limits but does not eliminate this.
- **Cluster risk**: many names dislocate together, so "diversified" reversion
  positions are correlated exactly when they lose.
- **Filter overfitting**: each optional filter is another knob; adding all of
  them on one window is a good way to curve-fit.

## Transaction-cost considerations

Higher trade frequency than trend following, especially at low
`entry_zscore`. Costs and slippage often exceed the per-trade edge on small
moves — sweep `slippage_bps` and watch `net_pnl` vs `gross_pnl`. Intraday
(`MIS`) has lower stamp duty and STT-on-sell-only but you pay brokerage.

## Look-ahead-bias considerations

`mean`, `std`, `Z`, RSI and Bollinger for bar *t* use closes up to and
including *t*; the decision is made on bar *t* and filled at *t*'s close.
Session VWAP accumulates only bars already seen. No future data is used.

## Survivorship-bias considerations

Single-instrument, so universe survivorship is not intrinsic — but a
hand-picked list of "range-bound" names selected with hindsight reintroduces
it. Choose the instrument list blind.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Regime analysis is essential here: report
performance in trending vs range-bound sub-periods separately, and validate
that the regime filter actually helps out-of-sample rather than just on the
fitting window.
