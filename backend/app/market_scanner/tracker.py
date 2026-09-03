"""Mark every LIVE recommendation against the real-time price and resolve it
when the target / stop / end-of-day is reached.

Price source, in order: the in-process Kite tick state (websocket), then a
batched REST quote for whatever the feed is missing. If neither has a
fresh price the row is flagged ``tracking_state = "STALE"`` and left LIVE -
it is never resolved on a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_scanner import marketdata as md
from app.models.market_scanner import ScannerAlert, ScanRecommendation

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_STALE_AFTER_S = 90.0


@dataclass
class TrackOutcome:
    checked: int = 0
    resolved_target: int = 0
    resolved_sl: int = 0
    resolved_neutral: int = 0
    invalidated: int = 0
    stale: int = 0
    filled: int = 0
    notes: list[str] = field(default_factory=list)


def _eod_cutoff(settings: Settings) -> dtime:
    raw = (settings.market_scanner_eod_flatten_ist or "15:20").split(":")
    return dtime(int(raw[0]), int(raw[1]))


def _live_price(token: str) -> float | None:
    try:
        from app.live.market_state import MARKET_STATE
    except Exception:  # noqa: BLE001
        return None
    tok = int(token)
    age = MARKET_STATE.age_seconds(tok)
    if age is not None and age <= _STALE_AFTER_S:
        return MARKET_STATE.last_price(tok)
    return None


def _resolve(
    db: Session, rec: ScanRecommendation, outcome: str, exit_price: float, now: datetime
) -> None:
    base = float(rec.entered_price if rec.entered_price is not None else rec.entry)
    sign = 1.0 if rec.direction == "LONG" else -1.0
    risk = abs(float(rec.entry) - float(rec.stop_loss)) or None
    pts = (exit_price - base) * sign
    rec.status = "EXPIRED"
    rec.outcome = outcome
    rec.exit_price = exit_price
    rec.exit_at = now
    rec.result_points = round(pts, 4)
    rec.result_pct = round(100.0 * pts / base, 4) if base else None
    rec.result_r = round(pts / risk, 3) if risk else None
    rec.last_ltp = exit_price
    rec.last_checked_at = now
    db.add(ScannerAlert(
        recommendation_id=rec.id, kind=outcome,
        title=f"{outcome} · {rec.direction} {rec.tradingsymbol}",
        body=(f"Exited {exit_price} ({rec.result_pct:+.2f}%"
              + (f", {rec.result_r:+.2f}R" if rec.result_r is not None else "") + ")."),
        payload={"recommendation_id": str(rec.id), "outcome": outcome,
                 "result_pct": rec.result_pct, "result_r": rec.result_r},
    ))


def run_tracker(db: Session, settings: Settings, *, now: datetime | None = None) -> TrackOutcome:
    now = now or datetime.now(UTC)
    now_ist = now.astimezone(IST)
    past_eod = now_ist.time() >= _eod_cutoff(settings)
    out = TrackOutcome()

    live: list[ScanRecommendation] = list(db.execute(
        select(ScanRecommendation).where(ScanRecommendation.status == "LIVE")
    ).scalars().all())
    if not live:
        return out

    # fill price gaps with one batched quote
    prices: dict[str, float | None] = {}
    misses: list[ScanRecommendation] = []
    for rec in live:
        p = _live_price(rec.instrument_token)
        prices[str(rec.id)] = p
        if p is None:
            misses.append(rec)
    if misses:
        client = md.get_client(db, settings)
        if client is not None:
            refs = sorted({f"{r.exchange}:{r.tradingsymbol}" for r in misses})
            q = md.batched_quotes(client, refs)
            for rec in misses:
                row = q.get(f"{rec.exchange}:{rec.tradingsymbol}")
                prices[str(rec.id)] = md.quote_ltp(row)

    for rec in live:
        out.checked += 1
        ltp = prices.get(str(rec.id))
        if ltp is None:
            rec.tracking_state = "STALE"
            rec.last_checked_at = now
            out.stale += 1
            continue
        rec.tracking_state = "OK"
        rec.last_ltp = ltp
        rec.last_checked_at = now
        long = rec.direction == "LONG"

        # pending LIMIT entry: fill when price trades through the level
        if rec.entered_price is None:
            if rec.entry_type == "LIMIT":
                touched = ltp <= float(rec.entry) if long else ltp >= float(rec.entry)
                if touched:
                    rec.entered_price = float(rec.entry)
                    out.filled += 1
                elif past_eod:
                    rec.status = "EXPIRED"
                    rec.outcome = "INVALIDATED"
                    rec.exit_at = now
                    rec.result_points = rec.result_pct = rec.result_r = 0.0
                    out.invalidated += 1
                    continue
                else:
                    continue
            else:
                rec.entered_price = float(rec.entry)

        base = float(rec.entered_price)
        fav = (ltp - base) / base * 100.0 * (1 if long else -1)
        rec.mfe_pct = round(max(float(rec.mfe_pct or 0.0), fav), 4)
        rec.mae_pct = round(min(float(rec.mae_pct or 0.0), fav), 4)

        hit_t = ltp >= float(rec.target_1) if long else ltp <= float(rec.target_1)
        hit_s = ltp <= float(rec.stop_loss) if long else ltp >= float(rec.stop_loss)
        if hit_s:
            _resolve(db, rec, "SL", float(rec.stop_loss), now)
            out.resolved_sl += 1
        elif hit_t:
            _resolve(db, rec, "TARGET", float(rec.target_1), now)
            out.resolved_target += 1
        elif past_eod:
            _resolve(db, rec, "NEUTRAL", ltp, now)
            out.resolved_neutral += 1

    db.commit()
    if out.resolved_target or out.resolved_sl or out.resolved_neutral or out.stale:
        logger.info("market_scan_tracker", **{
            k: getattr(out, k) for k in
            ("checked", "resolved_target", "resolved_sl", "resolved_neutral", "stale", "filled")
        })
    return out
