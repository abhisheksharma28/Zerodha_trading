"""Turn a canonical backtest payload into a short, honest plain-English
readout - the kind of summary a person actually wants when they open a
backtest: what was tested, what happened, and what to look at next.

Purely mechanical: it reads the numbers already in the payload. No model
call, no opinion beyond thresholds we can defend.
"""

from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _verdict(m: dict[str, Any], ruined: bool) -> tuple[str, str]:
    """(code, one-liner). code: ruined | avoid | marginal | tradeable | strong."""
    if ruined:
        return "ruined", "Account was wiped in the test window - do not trade this configuration."
    sharpe = _f(m.get("sharpe_ratio")) or 0.0
    ret = _f(m.get("return_pct")) or 0.0
    dd = abs(_f(m.get("max_drawdown_pct")) or 0.0)
    pf = _f(m.get("profit_factor")) or 0.0
    trades = int(_f(m.get("total_trades")) or 0)
    if trades < 20:
        return "insufficient", f"Only {trades} trades - not enough to judge; widen the universe or window."
    if sharpe >= 1.0 and ret > 0 and pf >= 1.3:
        return "strong", "Positive and reasonably risk-adjusted over the window (still validate out-of-sample)."
    if sharpe >= 0.4 and ret > 0:
        return "tradeable", "Net positive but modest risk-adjusted return - marginal edge at best."
    if ret > 0 and dd < 25:
        return "marginal", "Barely positive; the edge does not clearly beat the drawdown it takes."
    return "avoid", "Net loser or worse than buy-and-hold risk over the window on this configuration."


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    m = payload.get("metrics", {}) or {}
    cfg = payload.get("config", {}) or {}
    ruined = bool(payload.get("ruined"))
    code, headline = _verdict(m, ruined)

    used = len(payload.get("used_symbols") or [])
    uni_n = len(cfg.get("universe") or []) or used
    years = cfg.get("years")
    trades = int(_f(m.get("total_trades")) or 0)
    ret = _f(m.get("return_pct"))
    cagr = _f(m.get("cagr_pct"))
    sharpe = _f(m.get("sharpe_ratio"))
    sortino = _f(m.get("sortino_ratio"))
    dd = _f(m.get("max_drawdown_pct"))
    wr = _f(m.get("win_rate_pct"))
    pf = _f(m.get("profit_factor"))
    costs = _f(m.get("total_costs"))
    net = _f(m.get("net_pnl"))

    did = [
        f"Ran **{cfg.get('slug', '?')}** ({cfg.get('preset', 'balanced')} preset"
        + (", tuned params" if payload.get("tuned_overrides") else "")
        + f") over {cfg.get('universe_name', 'the universe')} "
        f"({used}/{uni_n} names had usable data) on the {cfg.get('timeframe', '?')} timeframe "
        f"for ~{years} years.",
        f"It opened **{trades} trades**"
        + (f", win rate {wr:.0f}%" if wr is not None else "")
        + (f", profit factor {pf:.2f}" if pf is not None else "")
        + (f", ~Rs {costs:,.0f} paid in costs" if costs else "")
        + ".",
    ]

    saw: list[str] = []
    if ret is not None:
        saw.append(
            f"**Return {ret:+.1f}%**"
            + (f" (CAGR {cagr:+.1f}%)" if cagr is not None else "")
            + (f", net P&L Rs {net:,.0f}" if net is not None else "")
            + "."
        )
    if sharpe is not None:
        saw.append(
            f"Risk-adjusted: Sharpe {sharpe:.2f}"
            + (f", Sortino {sortino:.2f}" if sortino is not None else "")
            + (f", max drawdown {abs(dd):.1f}%" if dd is not None else "")
            + "."
        )
    top = payload.get("top_symbols") or []
    bot = payload.get("bottom_symbols") or []
    if top:
        names = ", ".join(str(s.get("symbol")) for s in top[:3])
        saw.append(f"Carried by {names}" + (f"; worst: {str(bot[0].get('symbol'))}" if bot else "") + ".")
    if payload.get("skipped"):
        saw.append(f"{len(payload['skipped'])} names skipped (no/short data) - not survivorship-adjusted.")

    look = [
        "Check the equity curve for a single lucky run vs. steady compounding.",
        "Compare the return to just holding the index over the same window.",
        "Run the robustness suite (Monte-Carlo + walk-forward) before trusting the Sharpe.",
    ]
    if code in ("avoid", "marginal", "ruined", "insufficient"):
        look.append("Try the tuning grid or a different preset; this configuration is not ready.")
    for c in payload.get("caveats") or []:
        look.append(str(c))

    return {
        "verdict": code,
        "headline": headline,
        "what_we_did": did,
        "what_we_saw": saw,
        "what_to_look_at": look,
    }
