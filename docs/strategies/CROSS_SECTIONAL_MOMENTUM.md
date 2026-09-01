# Cross-Sectional Momentum

Slug: `cross-sectional-momentum` · Category: Momentum · Horizon: Positional ·
Complexity: High · Long / short / market-neutral capable.

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed, risk-free, or proven to be
> profitable in the future. Momentum strategies can suffer sharp drawdowns
> during violent reversals.

## Concept

Within a universe of stocks, recent relative performance tends to persist
over horizons of roughly one month to one year (Jegadeesh & Titman 1993, and
a large subsequent literature). The strategy ranks the universe by a blended
momentum score, holds an equal-weight book of the strongest names, and
optionally shorts the weakest, rebalancing on a fixed cadence.

## Mathematical logic

For instrument *i* at rebalance time *t*, for each lookback *L\_k* with
weight *w\_k*:

```
r_{i,k}      = P_{i,t} / P_{i,t-L_k} - 1
r_{i,k}      -= (P_{bench,t} / P_{bench,t-L_k} - 1)     # if use_relative_strength
r_{i,k}      /= realized_vol(P_i, L_k)                  # if volatility_adjusted
score_i      = Σ_k  w_k · r_{i,k}
```

Rank by `score_i` descending. Longs = top `num_long_positions`; shorts =
bottom `num_short_positions` (only if `allow_short`). Target an equal-weight
book:

```
target_qty_i = floor( (capital_allocation / n_long) / P_{i,t} )
```

capped at `max_position_size_pct` of `capital_allocation`. Short targets are
negative. Any currently-held name not in the new target set is closed.

## Entry / exit

There is no per-name entry/exit signal — the book is *rebalanced* on the
cadence (`rebalance_frequency`: daily / weekly / monthly). Between rebalances
the book is held unchanged. Eligibility (price, average volume, history,
volatility filters) is evaluated using only data available at the rebalance
bar; ranking is done on the prior completed period before the new bar is
ingested.

## Position sizing

Equal-weight by default. `capital_allocation` is the notional the book is
sized against and should match the backtest's `initial_capital` to avoid
leverage artefacts in the crude fill engine.

## Risk

`max_position_size_pct` caps a single name. There is no stop-loss —
cross-sectional momentum's risk control is diversification and the rebalance
cadence. A `max_volatility_pct` filter drops names that are too wild to size
sensibly. Consider pairing with an external regime filter.

## Parameters

`lookback_1/2/3`, `weight_1/2/3`, `num_long_positions`,
`num_short_positions`, `allow_short`, `rebalance_frequency`,
`volatility_adjusted`, `use_relative_strength`, `benchmark_symbol`,
`min_price`, `min_avg_volume`, `min_history_bars`, `max_volatility_pct`,
plus the common sizing/risk parameters. Full schema and ranges are served by
`GET /api/v1/strategy-library/cross-sectional-momentum`.

## Assumptions

- The universe is passed as the backtest instrument list; the benchmark must
  be present in the stream if `use_relative_strength` is on.
- Daily bars, aligned across instruments.
- Equal-weight, fully-invested longs; shorts assumed borrowable.
- No corporate-action adjustment beyond what the candle source provides.

## Known weaknesses

- **Momentum crashes**: fast, deep drawdowns when market leadership reverses
  (e.g. sharp rallies in beaten-down names after a selloff).
- **Turnover**: daily rebalancing generates heavy turnover; costs can erase
  the raw signal.
- **Crowding**: a widely-run signal degrades.
- **Short book**: borrow availability and cost are not modelled.

## Transaction-cost considerations

Turnover is the dominant cost driver. Compare `turnover_ratio` and
`total_costs` across daily/weekly/monthly cadence; the monthly book usually
keeps far more of its gross edge. Delivery (`CNC`) has no Zerodha brokerage
but higher STT and stamp duty than intraday.

## Look-ahead-bias considerations

Ranking runs on the *previous* completed period's closes for every
instrument before the current bar is ingested, so a name's own latest bar
cannot influence its selection. Filters use only trailing data. If you add
fundamentals or index-membership data, apply the same rule: as-of the
rebalance timestamp only.

## Survivorship-bias considerations

If the universe you pass is today's index constituents applied to the past,
the backtest is survivorship-biased (it never holds names that were later
delisted or dropped). Prefer historical point-in-time membership. If you
cannot, treat the results as an upper bound and say so.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Pay special attention to turnover/cost
analysis, regime analysis (trend vs reversal), and survivorship. Walk-forward
the lookback weights rather than fitting them once.
