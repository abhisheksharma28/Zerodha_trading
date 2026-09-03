"""Phase 1 — data-quality gate for the option chain + underlying bars.

Same philosophy as the Chinese Transformer DQ engine: severity-tagged, no
silent fills. An ``ERROR`` / ``CRITICAL`` finding sets ``ok = False`` and
the service refuses to emit a decision (it still returns the diagnostics so
the UI can show why).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainQualityReport, ChainSnapshot, QualityIssue

_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
_PENALTY = {"INFO": 0.0, "WARNING": 6.0, "ERROR": 22.0, "CRITICAL": 55.0}


def assess_chain(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *, now: datetime | None = None
) -> ChainQualityReport:
    issues: list[QualityIssue] = []
    n = len(snap.rows)

    if snap.spot <= 0:
        issues.append(QualityIssue("no_spot", "CRITICAL", "Underlying spot is missing or non-positive."))
    if n == 0:
        issues.append(QualityIssue("empty_chain", "CRITICAL", "No option strikes in the snapshot."))
        return _finalise(issues)
    if n < cfg.dq_min_strikes:
        issues.append(QualityIssue(
            "thin_chain", "ERROR",
            f"Only {n} strikes returned; need at least {cfg.dq_min_strikes} for reliable analysis."))

    # strike-grid gaps
    ks = [r.strike for r in snap.rows]
    step = snap.strike_step()
    big_gaps = sum(1 for a, b in zip(ks, ks[1:], strict=False) if b - a > step * 1.5 + 1e-6)
    if big_gaps:
        issues.append(QualityIssue(
            "strike_gaps", "WARNING",
            f"{big_gaps} gap(s) wider than 1.5x the {step:g}-point strike step — some strikes missing."))

    # missing / degenerate fields
    zero_oi = sum(1 for r in snap.rows if r.call_oi <= 0 and r.put_oi <= 0)
    if zero_oi / n * 100.0 > cfg.dq_max_zero_oi_pct:
        issues.append(QualityIssue(
            "oi_missing", "ERROR",
            f"{zero_oi}/{n} strikes have zero OI on both sides — OI feed looks broken."))
    elif zero_oi / n * 100.0 > cfg.dq_max_missing_oi_pct:
        issues.append(QualityIssue(
            "oi_sparse", "WARNING", f"{zero_oi}/{n} strikes have no OI on either side."))

    no_iv = sum(1 for r in snap.rows if r.call_iv is None and r.put_iv is None)
    if no_iv / n * 100.0 > cfg.dq_max_missing_iv_pct:
        issues.append(QualityIssue(
            "iv_sparse", "WARNING",
            f"IV unavailable for {no_iv}/{n} strikes — volatility metrics will be approximate."))

    bad_iv = sum(1 for r in snap.rows
                 for v in (r.call_iv, r.put_iv) if v is not None and (v <= 0 or v > 4.0))
    if bad_iv:
        issues.append(QualityIssue("iv_outliers", "WARNING",
                                   f"{bad_iv} implausible IV value(s) (<=0 or >400%) will be ignored."))

    # OHLC-style sanity on the LTPs we do have
    neg_ltp = sum(1 for r in snap.rows for v in (r.call_ltp, r.put_ltp)
                  if v is not None and v < 0)
    if neg_ltp:
        issues.append(QualityIssue("neg_price", "ERROR", f"{neg_ltp} negative option LTP(s)."))

    # staleness
    now = now or datetime.now(UTC)
    ao = snap.as_of if snap.as_of.tzinfo else snap.as_of.replace(tzinfo=UTC)
    age = (now - ao).total_seconds()
    if age > cfg.dq_stale_seconds:
        sev = "ERROR" if age > 4 * cfg.dq_stale_seconds else "WARNING"
        issues.append(QualityIssue("stale_chain", sev,
                                   f"Snapshot is {age:.0f}s old (limit {cfg.dq_stale_seconds:.0f}s)."))
    elif age < -120:
        issues.append(QualityIssue("future_timestamp", "WARNING",
                                   f"Snapshot timestamp is {-age:.0f}s in the future — clock skew?"))

    # expiry sanity
    if snap.dte < 0:
        issues.append(QualityIssue("expired", "CRITICAL", "Selected expiry is in the past."))
    elif snap.dte < 1:
        issues.append(QualityIssue("expiry_today", "WARNING",
                                   "Expiry is today — gamma / pin risk is extreme; treat output with care."))

    return _finalise(issues)


def assess_bars(bars: list, min_bars: int = 40) -> list[QualityIssue]:
    """Light check on the underlying candle series feeding market intelligence."""
    issues: list[QualityIssue] = []
    if len(bars) < min_bars:
        issues.append(QualityIssue("thin_history", "WARNING",
                                   f"Only {len(bars)} underlying bars; trend / regime metrics need ~{min_bars}."))
    bad = sum(1 for b in bars
              if min(float(b.open), float(b.high), float(b.low), float(b.close)) <= 0
              or float(b.high) < float(b.low))
    if bad:
        issues.append(QualityIssue("bad_ohlc", "ERROR", f"{bad} malformed underlying bar(s)."))
    return issues


def _finalise(issues: list[QualityIssue]) -> ChainQualityReport:
    score = max(0.0, 100.0 - sum(_PENALTY[i.severity] for i in issues))
    ok = not any(i.severity in ("ERROR", "CRITICAL") for i in issues)
    issues = sorted(issues, key=lambda i: -_RANK[i.severity])
    return ChainQualityReport(score=score, ok=ok, issues=issues)
