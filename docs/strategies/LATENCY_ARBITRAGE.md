# Latency Arbitrage (Lead-Lag)

Slug: `latency-arbitrage` · Category: Arbitrage · Horizon: Intraday ·
Complexity: High · Long / short · exactly two instruments.

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable.

## Important: what this is and is not

This is **not** co-located, tick-level HFT latency arbitrage. That requires
direct exchange feeds, co-location, and an execution path measured in
microseconds — none of which this platform has. It runs on OHLCV **bars**
over a single retail broker feed with order-routing latency of tens of
milliseconds at best, so any genuine speed advantage is gone before this
strategy can act.

What it actually implements is the retail-accessible cousin: a very
short-horizon **lead-lag convergence** trade. Given two tightly correlated
instruments (an index and its most liquid constituent; the same name on two
exchanges; an index and its ETF), when the "leader" has moved and the
"laggard" has not yet caught up, it takes the laggard in the leader's
direction and exits as the return gap closes.

## Mathematical logic

```
lead_ret_t = P_lead,t / P_lead,t-signal_lookback - 1
lag_ret_t  = P_lag,t  / P_lag,t-signal_lookback  - 1
gap_bps_t  = (lead_ret_t - lag_ret_t) · 10_000
corr_t     = Pearson corr of the two return series over corr_lookback
```

Only act when both legs are time-aligned. **Enter** (flat only) when
`corr_t ≥ min_correlation` and `|gap_bps_t| ≥ divergence_bps`: buy the
laggard if `gap_bps_t > 0`, sell it if `gap_bps_t < 0` (and `allow_short`).

## Entry / exit

Exit when `|gap_bps_t| ≤ exit_gap_bps` (converged — take it), when
`|gap_bps_t| ≥ stop_gap_bps` (it was a real divergence, not a lag — abandon),
or after `max_holding_bars`.

## Position sizing

Common `sizing_method`. Only the laggard is traded (the leader is data
only). Product `MIS`.

## Risk

`stop_gap_bps` caps the loss when the "lag" turns out to be a genuine
repricing. `max_holding_bars` bounds time in trade. The correlation guard is
a hard prerequisite — without it the strategy trades noise.

## Parameters

`leader_symbol`, `signal_lookback`, `divergence_bps`, `exit_gap_bps`,
`stop_gap_bps`, `max_holding_bars`, `corr_lookback`, `min_correlation`,
`allow_short`. Full schema:
`GET /api/v1/strategy-library/latency-arbitrage`.

## Assumptions

- Exactly two instruments, **time-aligned intraday bars**.
- One instrument genuinely leads the other on the chosen timeframe.
- The relationship is stable over the (short) holding period.

## Known weaknesses

- **No real edge at this granularity**: the modelled gap is frequently
  already arbitraged away by faster participants; net of costs the
  expectation is often negative.
- **Decoupling**: a "lag" that is actually permanent news never reverts.
- **Cost dominance**: intraday costs and slippage typically exceed the
  per-trade gap being captured.
- **Which is the leader** is itself unstable and can flip.

## Transaction-cost considerations

The most cost-sensitive template in the library, alongside ORB. The captured
move is a handful of basis points; `slippage_bps` alone can make it
unprofitable. Always sweep slippage and compare `net_pnl`/`gross_pnl`;
treat a positive result at zero cost as meaningless.

## Look-ahead-bias considerations

Returns, the gap, and the rolling correlation for bar *t* use prices up to
and including *t* only, and both legs must be aligned. No future bar enters
the signal. Covered by an explicit look-ahead test and a correlation-guard
test.

## Survivorship-bias considerations

Choosing the pair (and which leg leads) with hindsight is a survivorship
decision. Establish the lead-lag relationship on an out-of-sample window
first.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Be ruthless about cost and slippage
sensitivity; require the strategy to survive pessimistic slippage
out-of-sample before taking it seriously. Re-check the lead-lag direction
and correlation through the test period.
