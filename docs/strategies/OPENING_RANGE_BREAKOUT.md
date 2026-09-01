# Opening Range Breakout (ORB)

Slug: `opening-range-breakout` · Category: Breakout · Horizon: Intraday ·
Complexity: Medium · Long / short capable · NSE session-aware (Asia/Kolkata).

> Research-backed strategy template requiring validation, optimization and
> out-of-sample testing. **Not** guaranteed or proven profitable. Breakout
> strategies are very sensitive to transaction costs and false breakouts.

## Concept

The first minutes of the NSE session often set the day's range; a decisive
break of that range on volume is a widely-watched intraday pattern. The
strategy defines the opening range, waits for it to lock, then trades a
breakout with volume confirmation and optional VWAP / benchmark filters, and
always flattens before a configured square-off time.

## Mathematical logic

For each instrument, each trading day, over bars with timestamp in
`[opening_range_start, opening_range_end)` (IST):

```
OR_high  = max(high)     OR_low  = min(low)
OR_vol   = Σ volume      mean_OR_vol = OR_vol / (# OR bars)
VWAP_t   = Σ(typical·vol) / Σ vol     over the whole day so far
```

After the range locks: **long** when `close_t > OR_high` and
`volume_t ≥ volume_multiplier · mean_OR_vol` and (if `use_vwap_filter`)
`close_t > VWAP_t` and (if `market_trend_filter`) the benchmark is not in a
downtrend. **Short** is the mirror below `OR_low`.

## Entry / exit

On entry the stop is fixed: `entry − stop_distance` for a long, where
`stop_distance = atr_stop_mult · ATR` if `atr_stop_mult > 0` else
`entry · stop_loss_pct/100`. Optional target `entry · (1 ± target_pct/100)`
and optional trailing stop `trailing_stop_pct` from the high-water mark.
**Every open position is force-closed at `square_off_time`** and no new
entries are taken after it — the strategy never holds overnight in intraday
mode.

## Position sizing

Common `sizing_method` (`fixed_capital` in the balanced preset). Product is
`MIS` (intraday).

## Risk

Hard per-day controls: `max_long_trades_per_day`, `max_short_trades_per_day`,
`max_trades_per_day` (overall), and `max_daily_loss_pct` — once realised
intraday P&L hits `-max_daily_loss_pct` of `capital_allocation`, no further
entries that day. `allowed_weekdays` restricts trading days. Forced
square-off is non-negotiable.

## Parameters

`opening_range_start`, `opening_range_end`, `square_off_time`,
`allowed_weekdays`, `volume_multiplier`, `use_vwap_filter`,
`market_trend_filter`, `atr_period`, `atr_stop_mult`, `stop_loss_pct`,
`target_pct`, `trailing_stop_pct`, `max_long_trades_per_day`,
`max_short_trades_per_day`, `max_trades_per_day`, `max_daily_loss_pct`,
`allow_short`, plus common sizing/regime parameters. Full schema:
`GET /api/v1/strategy-library/opening-range-breakout`.

## Assumptions

- **Intraday bars** (1–5 minute) that actually cover the opening range and
  run through the square-off time. Daily bars make this strategy meaningless.
- Timestamps are timezone-aware and interpreted in Asia/Kolkata.
- One NSE-style session per day; instruments with different sessions need
  the range/square-off times adjusted.
- Benchmark intraday bars in the stream if `market_trend_filter` is on.

## Known weaknesses

- **False breakouts**: price pokes past the range and reverses straight
  through the stop — the dominant loss mode.
- **Cost sensitivity**: the intraday edge per trade is small relative to
  brokerage + STT + slippage.
- **Gap days**: a large opening gap produces a very wide range (oversized
  stop) or no clean break at all.
- **Parameter fragility**: range length, volume multiplier and stop are all
  easy to overfit to one sample.

## Transaction-cost considerations

This is the template where costs matter most. Always sweep `slippage_bps`
against a pessimistic value for the name's liquidity, and compare
`net_pnl`/`gross_pnl`. Intraday STT is sell-side only but brokerage and
stamp duty still apply per order; more trades per day is more cost.

## Look-ahead-bias considerations

The range only uses bars inside the opening window; entries are only
evaluated after the window has closed. VWAP accumulates only bars already
seen. The stop/target are set from entry-bar data. No later bar in the day
influences an earlier decision — this is covered by an explicit look-ahead
test.

## Survivorship-bias considerations

Single-instrument. A hand-picked list of names that "broke out well" in the
sample is survivorship in disguise; choose the instrument list without
inspecting historical breakouts.

## Recommended research methodology

See `RESEARCH_METHODOLOGY.md`. Weight slippage-sensitivity and cost analysis
heavily; test across many instruments and a long date range (breakout hit
rates are noisy on small samples); check performance separately on trending
vs range days.
