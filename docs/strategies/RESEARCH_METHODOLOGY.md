# Strategy research methodology

The templates in this library are **established quantitative strategy
families with academic and institutional precedent**. They are **not**
guaranteed, risk-free, or proven to be profitable in the future, and nothing
in this repository should be read as investment advice. A template is a
starting point for research — the work of deciding whether it has an edge in
a given market, at a given cost level, over a given period is yours.

Evaluate a template roughly in this order. Stop early if it fails a step —
there is no point optimising a strategy that does not survive costs.

## 1. In-sample testing

Run the backtest on a training window with the platform's default Indian
cost model **on**. Look at the full metric set (net vs gross P&L, Sharpe,
Sortino, Calmar, max drawdown, profit factor, win rate, turnover), not just
total return. A strategy that only works gross is not a strategy.

## 2. Out-of-sample testing

Hold back a contiguous, later period the parameters never touched. Re-run
with the *same* parameters. Expect materially worse numbers than in-sample;
be suspicious if they are dramatically worse (overfit) or suspiciously
similar (leakage).

## 3. Walk-forward testing

Repeatedly: fit parameters on a rolling training window, trade the next
(unseen) window, roll forward. The concatenated out-of-sample equity curve
is the honest estimate of live behaviour. The platform stores each run as an
immutable strategy version, which makes this bookkeeping tractable.

## 4. Transaction-cost analysis

Re-run with the cost model set to different assumptions (see the `costs`
block of the run request): your actual brokerage, higher/lower slippage,
delivery vs intraday. Plot net P&L against slippage in basis points. If a
small change in assumed slippage flips the result, the edge is inside the
noise.

## 5. Slippage sensitivity

Specifically sweep `slippage_bps` from 0 to a pessimistic value for the
instrument's liquidity. Breakout and intraday strategies are the most
fragile here.

## 6. Parameter sensitivity

Vary each parameter one at a time around its chosen value. A robust strategy
degrades gracefully; a fragile one has a single sharp peak (a sign you fit
the noise). Prefer a broad, gently-sloping region over the global maximum.

## 7. Drawdown analysis

Look at the drawdown curve, the longest underwater period, and the maximum
consecutive losses — not just the max drawdown number. Ask whether you could
actually hold the position through that stretch with real capital.

## 8. Regime analysis

Segment results by market regime (trending vs range-bound, high vs low
volatility, pre/post a structural event). Momentum and trend strategies tend
to earn in trends and bleed in chop; mean-reversion and pairs do the
opposite. Know which regime you are betting on.

## 9. Monte Carlo analysis

Where available, resample the trade sequence (block bootstrap) to get a
distribution of outcomes rather than a single path. The single historical
path is one draw; the distribution tells you how lucky or unlucky it was.

## Biases to actively defend against

- **Look-ahead bias** — using information not available at decision time.
  Every template here consumes bars strictly in order through `on_bar` and
  keeps its own causal rolling buffers; the repo has explicit look-ahead
  tests. Preserve this when you modify a template.
- **Survivorship bias** — testing a universe of *today's* constituents over
  the past. If historical index membership is not available, the backtest UI
  and these docs say so; treat cross-sectional results as optimistic.
- **Overfitting** — the platform never auto-optimises parameters against the
  whole dataset and presents the result as robustness. Neither should you.
  The in-sample / out-of-sample / walk-forward split exists for this reason.

## The goal

Robustness, not a maximal historical P&L number. A strategy you understand,
that degrades gracefully, and that survives realistic costs out-of-sample is
worth more than a curve-fit that looks spectacular on one window.
