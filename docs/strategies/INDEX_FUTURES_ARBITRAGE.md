# Index / Futures Arbitrage (Cash-Futures Basis)

Slug: `index-futures-arbitrage` · Category: Arbitrage · Horizon:
Market-neutral · Complexity: High · Long / short / market-neutral · exactly
two instruments (spot + future).

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable. Carry
> assumptions may be wrong and the basis can stay dislocated.

## Concept

By no-arbitrage, an index (or stock) future should trade at the spot price
compounded at the cost of carry:

```
F* = S · exp((r - q) · T)
```

where `S` is spot, `r` the annualised risk-free rate, `q` the annualised
dividend yield, and `T` the time to expiry in years. When the observed
future `F` is rich versus `F*` the strategy sells the future and buys the
spot leg; when cheap, the reverse — holding until the basis converges (it
must, by expiry).

## Mathematical logic

```
T          = days_to_expiry / 365   (or from expiry_date and the bar date)
F*         = S · exp((risk_free_rate_pct - dividend_yield_pct)/100 · T)
deviation  = (F - F*) / S · 100      (percent of spot)
```

**Enter** (flat): if `deviation ≥ entry_deviation_pct` the future is rich →
SELL future / BUY spot. If `deviation ≤ -entry_deviation_pct` → BUY future /
SELL spot.

## Entry / exit

Unwind both legs when `|deviation| ≤ exit_deviation_pct` (converged), when
`|deviation| ≥ stop_deviation_pct` (model or inputs are wrong — stop), after
`max_holding_bars`, or `close_days_before_expiry` days before expiry
(whichever comes first). Only acts on bars where the two legs are
time-aligned.

## Position sizing

`qty_future` from the common `sizing_method`, then **rounded down to a
multiple of `futures_lot_size`**. The spot leg is held 1:1 in point terms
(`qty_spot = qty_future`). Spot leg on `exchange` (default NSE), futures leg
on `futures_exchange` (default NFO), product `NRML`.

## Risk

`stop_deviation_pct` guards against a wrong rate/dividend assumption or a
structural dislocation. Forced flatten before expiry avoids delivery /
settlement mechanics. Market-neutral by construction, but not risk-free (see
weaknesses).

## Parameters

`spot_symbol`, `risk_free_rate_pct`, `dividend_yield_pct`, `expiry_date`,
`days_to_expiry`, `entry_deviation_pct`, `exit_deviation_pct`,
`stop_deviation_pct`, `futures_lot_size`, `close_days_before_expiry`,
`max_holding_bars`, `exchange`, `futures_exchange`. Full schema:
`GET /api/v1/strategy-library/index-futures-arbitrage`.

## Assumptions

- Two time-aligned instruments: the spot/cash leg and its future.
- A **correct** expiry date (or `days_to_expiry`) and carry inputs — these
  drive every signal.
- The spot leg is actually tradeable (an index itself is not; use its ETF,
  e.g. NIFTYBEES, or a single-stock cash position).
- Constant `r` and `q` over the holding period; no intra-quarter dividend
  timing modelled.

## Known weaknesses

- **Financing / borrow cost** can exceed the captured basis, especially for
  the reverse (long-future / short-cash) trade.
- **Input error**: a wrong rate or dividend yield biases `F*` and therefore
  every signal in the same direction.
- **Imperfect hedge**: `futures_lot_size` granularity and the 1:1 point
  assumption leave residual directional exposure.
- **Event dislocation**: the basis can widen further around expiry,
  dividends or index rebalancing before it converges — you may be stopped
  out at the worst point.

## Transaction-cost considerations

Two legs each way. Futures exchange charges and STT-on-sell differ from
equity; the spot leg carries its own equity charges. The gross basis
captured is typically a fraction of a percent, so cost and slippage
assumptions decide profitability — sweep them and compare
`net_pnl`/`gross_pnl`.

## Look-ahead-bias considerations

`F*` for bar *t* uses only `S_t`, the (fixed) carry inputs, and the time to
expiry as of *t*. The deviation and all exit conditions use bar *t* data
only, with the legs aligned. No future price enters the fair value.

## Survivorship-bias considerations

Not a universe strategy, so classic survivorship does not apply; but
back-testing only the front-month contract of an index that always had a
liquid future is a mild selection effect — be explicit about which contract
series and period you used.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Additionally: sensitivity-test `r` and `q`
(re-run with plausible high/low values and confirm the sign of the edge is
stable); analyse behaviour separately in the last week before expiry; model
your actual financing cost in the `costs` block.
