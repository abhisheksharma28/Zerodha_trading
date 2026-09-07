"""Render an outbox row into the final Telegram HTML message.

Formatting lives here (not at the event site) so a row stores only
``kind`` + ``title`` + ``body`` + a structured ``payload``, and the wording
can change without touching the scanner / tracker / engine or the DB.
Every interpolated value goes through :func:`_esc`.
"""

from __future__ import annotations

import html
from typing import Any

from app.models.notifications import (
    KIND_DAILY_SUMMARY,
    KIND_IDEA_NEW,
    KIND_IDEA_OUTCOME,
    KIND_PAPER_FILL,
    KIND_TEST,
)


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=False)


def _num(v: Any, dp: int = 2) -> str:
    try:
        return f"{float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return "-"


def _signed(v: Any, dp: int = 2, suffix: str = "") -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{f:+,.{dp}f}{suffix}"


def _rupee(v: Any) -> str:
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return "-"


_OUTCOME_EMOJI = {
    "TARGET": "✅", "SL": "🛑", "NEUTRAL": "⚪️", "INVALIDATED": "🚫",
}
_DIR_EMOJI = {"LONG": "🟢", "SHORT": "🔴", "BUY": "🟢", "SELL": "🔴"}


def _idea_new(p: dict[str, Any]) -> str:
    dir_ = str(p.get("direction", "")).upper()
    head = f"{_DIR_EMOJI.get(dir_, '🎯')} <b>New idea · {_esc(dir_)} {_esc(p.get('symbol'))}</b>"
    style = " · ".join(
        _esc(x) for x in (p.get("trade_style"), p.get("horizon"), p.get("grade")) if x
    )
    lines = [head]
    if style:
        lines.append(f"<i>{style}</i>")
    if p.get("setup_type"):
        lines.append(_esc(p["setup_type"]))
    lines.append(
        f"Entry <b>{_num(p.get('entry'))}</b>  SL <b>{_num(p.get('stop_loss'))}</b>  "
        f"T1 <b>{_num(p.get('target_1'))}</b>"
        + (f"  T2 {_num(p['target_2'])}" if p.get("target_2") else "")
    )
    tail = []
    if p.get("rr") is not None:
        tail.append(f"R:R {_num(p['rr'], 2)}")
    if p.get("risk_pct") is not None:
        tail.append(f"risk {_num(p['risk_pct'], 2)}%")
    if p.get("confidence") is not None:
        tail.append(f"confidence {_num(p['confidence'], 0)}")
    if tail:
        lines.append("  ·  ".join(tail))
    return "\n".join(lines)


def _idea_outcome(p: dict[str, Any]) -> str:
    outcome = str(p.get("outcome", "")).upper()
    emoji = _OUTCOME_EMOJI.get(outcome, "•")
    head = (
        f"{emoji} <b>{_esc(outcome)} · {_esc(str(p.get('direction', '')).upper())} "
        f"{_esc(p.get('symbol'))}</b>"
    )
    lines = [head]
    if p.get("horizon"):
        lines.append(f"<i>{_esc(p['horizon'])}</i>")
    bits = []
    if p.get("exit_price") is not None:
        bits.append(f"exit {_num(p['exit_price'])}")
    if p.get("result_pct") is not None:
        bits.append(_signed(p["result_pct"], 2, "%"))
    if p.get("result_r") is not None:
        bits.append(_signed(p["result_r"], 2, "R"))
    if bits:
        lines.append("  ·  ".join(bits))
    return "\n".join(lines)


def _paper_fill(p: dict[str, Any]) -> str:
    side = str(p.get("side", "")).upper()
    head = (
        f"{_DIR_EMOJI.get(side, '•')} <b>{_esc(side)} {_esc(p.get('quantity'))} "
        f"{_esc(p.get('symbol'))}</b> @ {_num(p.get('price'))}"
    )
    lines = [head]
    meta = " · ".join(
        _esc(x) for x in (p.get("product"), p.get("source_label")) if x
    )
    if meta:
        lines.append(f"<i>{meta}</i>")
    bits = []
    if p.get("value") is not None:
        bits.append(f"value {_rupee(p['value'])}")
    if p.get("charges") is not None:
        bits.append(f"charges {_num(p['charges'])}")
    if bits:
        lines.append("  ·  ".join(bits))
    if p.get("realized_pnl"):
        lines.append(f"realised P&amp;L {_signed(p['realized_pnl'], 0)}")
    return "\n".join(lines)


def _daily_summary(p: dict[str, Any]) -> str:
    lines = [f"📊 <b>Paper account · {_esc(p.get('date', 'today'))}</b>"]
    lines.append(
        f"Net worth <b>{_rupee(p.get('net_worth'))}</b>   "
        f"Day P&amp;L {_signed(p.get('day_pnl'), 0)}"
    )
    tot = f"Total P&amp;L {_signed(p.get('total_pnl'), 0)}"
    if p.get("total_pct") is not None:
        tot += f" ({_signed(p['total_pct'], 2, '%')})"
    lines.append(tot)
    lines.append(
        f"Open positions {_esc(p.get('open_positions', 0))}   "
        f"Fills today {_esc(p.get('fills_today', 0))}"
    )
    lines.append(
        f"Scanner: {_esc(p.get('ideas_live', 0))} live · "
        f"{_esc(p.get('ideas_target', 0))}✅ / {_esc(p.get('ideas_sl', 0))}🛑 / "
        f"{_esc(p.get('ideas_neutral', 0))}⚪️ today"
    )
    return "\n".join(lines)


def _test(_: dict[str, Any]) -> str:
    return (
        "✅ <b>Test notification</b>\n"
        "Telegram is wired up. You'll get new scanner ideas, idea outcomes, "
        "paper fills and a daily summary here."
    )


_RENDERERS = {
    KIND_IDEA_NEW: _idea_new,
    KIND_IDEA_OUTCOME: _idea_outcome,
    KIND_PAPER_FILL: _paper_fill,
    KIND_DAILY_SUMMARY: _daily_summary,
    KIND_TEST: _test,
}


def render(kind: str, title: str, body: str, payload: dict[str, Any] | None) -> str:
    """Final HTML for a Telegram message. Falls back to ``title``/``body``
    for an unknown kind or a thin payload."""
    fn = _RENDERERS.get(kind)
    if fn is not None:
        try:
            return fn(payload or {})
        except Exception:  # noqa: BLE001 - never let a formatting bug drop the message
            pass
    out = f"<b>{_esc(title)}</b>"
    if body:
        out += f"\n{_esc(body)}"
    return out
