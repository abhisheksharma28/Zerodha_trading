# Trend Following

Slug: `trend-following` · Category: Trend · Horizon: Swing / Positional ·
Complexity: Medium · Long / short capable.

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable. Trend
> strategies can experience prolonged periods of whipsaw.

## Concept

Asset prices trend more often than a random walk predicts (the basis of
managed-futures / CTA programs). The strategy is long while a fast moving
average leads a slow one and price confirms, flat or short otherwise, with
ATR-based risk control.

## Mathematical logic

```
fast_t = MA(close, fast_period)      # SMA or EMA
slow_t = MA(close, slow_period)
atr_t  = Wilder_ATR(high, low, close, atr_period)
strength_t = |fast_t - slow_t| / slow_t · 100      (percent)
vol_t  = stdev of simple returns over 20 bars · 100 (percent)
```

**Long entry** when all hold: `fast` crosses above `slow` (i.e.
`fast_{t-1} ≤ slow_{t-1}` and `fast_t > slow_t`); `close_t > slow_t` (if
`use_price_filter`); `strength_t ≥ trend_strength_min_pct`;
`vol_min_pct ≤ vol_t ≤ vol_max_pct`; the market-regime filter (if enabled)
permits longs. **Short entry** is the mirror when `allow_short`.

## Entry / exit

Exit a long on any of: opposite crossover; hard stop
`close ≤ entry − atr_stop_mult · ATR_entry`; trailing stop
`close ≤ high_water − trailing_atr_mult · ATR_entry`; take-profit
`close ≥ entry · (1 + take_profit_pct/100)`; `max_holding_bars` reached.
Stops use the ATR measured **at entry**, fixed for the life of the trade, so
a violent bar cannot widen the stop out from under the position.

## Position sizing

Pluggable (`sizing_method`): fixed quantity, fixed capital, equal weight,
**volatility-adjusted** (exposure scales down as realized volatility rises
toward `target_volatility_pct`), or **risk-per-trade** (quantity =
`risk_per_trade_pct` of `capital_allocation` ÷ stop distance). Capped by
`max_position_size_pct`.

## Risk

ATR hard stop + optional ATR trailing stop + optional max holding period.
Volatility-adjusted sizing is the recommended default for keeping per-trade
risk roughly constant across regimes.

## Parameters

`ma_type`, `fast_period`, `slow_period`, `atr_period`,
`trend_strength_min_pct`, `vol_min_pct`, `vol_max_pct`, `use_price_filter`,
`allow_short`, `atr_stop_mult`, `trailing_atr_mult`, `take_profit_pct`,
`max_holding_bars`, plus common sizing/risk/regime parameters. Full schema:
`GET /api/v1/strategy-library/trend-following`.

## Assumptions

- One instrument per strategy instance (run several for a portfolio).
- Fills at the signal bar's close (plus modelled slippage).
- EMA is seeded with the SMA of the first `period` points; a crossover that
  occurs exactly at a hard price discontinuity may be missed by one bar.

## Known weaknesses

- **Whipsaw**: range-bound markets generate repeated small losing crossovers.
- **Lag**: entries are late and open profit is given back around reversals.
- **Gap risk**: an overnight gap through the ATR stop realises a larger loss
  than modelled.
- Parameter-sensitive: fast/slow periods are easy to overfit.

## Transaction-cost considerations

Fewer, longer trades than most templates, so costs are usually a smaller
fraction of P&L — but a whippy parameter set with many crossovers reverses
that. Check `total_trades` and `total_costs`; a good trend config trades
rarely.

## Look-ahead-bias considerations

`fast`/`slow`/`ATR` for bar *t* use closes up to and including *t*; the
crossover check compares against the values recomputed from closes up to
*t−1*. No future bar is referenced. Exit checks run on the current bar only.

## Survivorship-bias considerations

Single-instrument, so classic universe survivorship does not apply, but if
you screen a list of "trending stocks" chosen with hindsight you reintroduce
it. Pick the instrument list without looking at which names trended.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Emphasise parameter-sensitivity (broad plateau
over sharp peak) and regime analysis (measure trend-vs-chop performance
separately). Walk-forward the moving-average periods.
