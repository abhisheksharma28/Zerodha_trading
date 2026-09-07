"""The one entry point for outbound notifications.

* Event sites call :func:`enqueue` - a guarded INSERT on their own
  transaction, never a network call, never raises.
* The background loop calls :func:`dispatch_pending` and
  :func:`maybe_send_daily_summary`.
* The API calls :func:`config_status`, :func:`set_config`, :func:`send_test`,
  :func:`recent`, :func:`detect_chats`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.notifications import (
    KIND_DAILY_SUMMARY,
    KIND_IDEA_NEW,
    KIND_PAPER_FILL,
    KIND_TEST,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    Notification,
    NotificationConfig,
)
from app.notifications import format as fmt
from app.notifications import telegram

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_CONFIG_LOCK = 776631  # serialize the one-time config-row create
_MAX_ATTEMPTS = 5
_GRADE_RANK = {"A": 3, "B": 2, "C": 1}
_SUMMARY_AFTER = dtime(15, 35)

# per-kind -> the NotificationConfig column that gates it
_KIND_TOGGLE = {
    KIND_IDEA_NEW: "notify_new_ideas",
    "IDEA_OUTCOME": "notify_idea_outcomes",
    KIND_PAPER_FILL: "notify_paper_fills",
    KIND_DAILY_SUMMARY: "notify_daily_summary",
}


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def get_config(db: Session) -> NotificationConfig:
    """The single notification_config row (created on first use)."""
    cfg = db.execute(select(NotificationConfig).limit(1)).scalar_one_or_none()
    if cfg is not None:
        return cfg
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CONFIG_LOCK})
    cfg = db.execute(select(NotificationConfig).limit(1)).scalar_one_or_none()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg)
        # flush, not commit: the row rides the caller's transaction. An
        # event site calls this mid-transaction and must not have its work
        # committed out from under it; the scheduler / API call db.commit()
        # themselves. The advisory lock is xact-scoped and auto-releases.
        db.flush()
    return cfg


def _config_dict(cfg: NotificationConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "telegram_chat_id": cfg.telegram_chat_id,
        "notify_new_ideas": cfg.notify_new_ideas,
        "notify_idea_outcomes": cfg.notify_idea_outcomes,
        "notify_paper_fills": cfg.notify_paper_fills,
        "notify_daily_summary": cfg.notify_daily_summary,
        "idea_min_grade": cfg.idea_min_grade,
    }


def config_status(db: Session, settings: Settings) -> dict[str, Any]:
    cfg = get_config(db)
    token = bool(settings.telegram_bot_token)
    bot_username: str | None = None
    bot_error: str | None = None
    if token:
        try:
            bot_username = telegram.get_me(settings.telegram_bot_token).get("username")
        except telegram.TelegramError as exc:
            bot_error = str(exc)
    return {
        "config": _config_dict(cfg),
        "token_present": token,
        "connected": bool(token and cfg.telegram_chat_id and not bot_error),
        "bot_username": bot_username,
        "bot_error": bot_error,
    }


def _as_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


_EDITABLE = {
    "enabled": _as_bool,
    "telegram_chat_id": lambda v: (str(v).strip() or None),
    "notify_new_ideas": _as_bool,
    "notify_idea_outcomes": _as_bool,
    "notify_paper_fills": _as_bool,
    "notify_daily_summary": _as_bool,
    "idea_min_grade": lambda v: str(v).strip().upper(),
}


def set_config(db: Session, patch: dict[str, Any]) -> NotificationConfig:
    cfg = get_config(db)
    for key, caster in _EDITABLE.items():
        if key not in patch:
            continue
        val = caster(patch[key])
        if key == "idea_min_grade" and val not in _GRADE_RANK:
            raise ValidationError("idea_min_grade must be A, B or C")
        setattr(cfg, key, val)
    db.commit()
    db.refresh(cfg)
    return cfg


# --------------------------------------------------------------------------
# enqueue - called from event sites, must never raise
# --------------------------------------------------------------------------

def enqueue(
    db: Session,
    kind: str,
    *,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
    grade: str | None = None,
) -> None:
    """Record an outbound notification on the caller's transaction. Applies
    the master switch, the per-kind toggle and (for new ideas) the grade
    filter - a filtered-out message is still stored as ``skipped`` for the
    log. Wrapped in a savepoint so a failure here can never poison the
    caller's transaction."""
    try:
        with db.begin_nested():
            cfg = get_config(db)
            status = STATUS_PENDING
            reason: str | None = None
            toggle = _KIND_TOGGLE.get(kind)
            if not cfg.enabled:
                status, reason = STATUS_SKIPPED, "notifications disabled"
            elif toggle and not getattr(cfg, toggle):
                status, reason = STATUS_SKIPPED, f"{toggle} off"
            elif (
                kind == KIND_IDEA_NEW
                and grade
                and _GRADE_RANK.get(grade.upper(), 0)
                < _GRADE_RANK.get(cfg.idea_min_grade, 0)
            ):
                status, reason = STATUS_SKIPPED, f"grade {grade} below {cfg.idea_min_grade}"
            db.add(
                Notification(
                    kind=kind,
                    title=title[:200],
                    body=body,
                    payload=payload or {},
                    status=status,
                    last_error=reason,
                )
            )
    except Exception:  # noqa: BLE001 - notifications must never break a trade path
        logger.exception("notification_enqueue_failed", kind=kind)


# --------------------------------------------------------------------------
# delivery - called from the notifications loop
# --------------------------------------------------------------------------

def dispatch_pending(db: Session, settings: Settings, limit: int = 20) -> dict[str, int]:
    rows = list(
        db.execute(
            select(Notification)
            .where(
                Notification.status.in_((STATUS_PENDING, STATUS_FAILED)),
                Notification.attempts < _MAX_ATTEMPTS,
            )
            .order_by(Notification.created_at.asc())
            .limit(limit)
        ).scalars().all()
    )
    out = {"sent": 0, "failed": 0, "skipped": 0}
    if not rows:
        return out

    token = settings.telegram_bot_token
    chat_id = get_config(db).telegram_chat_id
    for row in rows:
        if not token or not chat_id:
            row.status = STATUS_SKIPPED
            row.last_error = "no bot token" if not token else "no chat id"
            out["skipped"] += 1
            continue
        text_html = fmt.render(row.kind, row.title, row.body, row.payload)
        row.attempts += 1
        try:
            telegram.send_message(token, chat_id, text_html)
        except telegram.TelegramError as exc:
            row.status = STATUS_FAILED
            row.last_error = str(exc)[:400]
            out["failed"] += 1
        else:
            row.status = STATUS_SENT
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            out["sent"] += 1
    db.commit()
    if out["sent"] or out["failed"]:
        logger.info("notifications_dispatched", **out)
    return out


def send_test(db: Session, settings: Settings) -> dict[str, Any]:
    """Enqueue a TEST message bypassing the toggles and deliver it now."""
    row = Notification(kind=KIND_TEST, title="Test notification", body="", payload={},
                       status=STATUS_PENDING)
    db.add(row)
    db.commit()
    dispatch_pending(db, settings, limit=5)
    db.refresh(row)
    return {"ok": row.status == STATUS_SENT, "status": row.status, "error": row.last_error}


# --------------------------------------------------------------------------
# daily summary
# --------------------------------------------------------------------------

def _ist_day_start_utc(now_ist: datetime) -> datetime:
    return now_ist.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def maybe_send_daily_summary(db: Session, settings: Settings, *, now: datetime | None = None) -> bool:
    cfg = get_config(db)
    if not cfg.enabled or not cfg.notify_daily_summary:
        return False
    now_ist = (now or datetime.now(UTC)).astimezone(IST)
    if now_ist.weekday() >= 5 or now_ist.time() < _SUMMARY_AFTER:
        return False
    today = now_ist.date().isoformat()
    if cfg.last_summary_day == today:
        return False

    from app.models.paper_account import PaperPosition, PaperTrade
    from app.paper_account import engine as pa_engine
    from app.paper_account import service as pa_service

    payload: dict[str, Any] = {"date": today}
    try:
        summ = pa_service.summary(db, settings)
        acct_id = pa_engine.get_or_create_account(db).id
        payload["net_worth"] = summ.get("net_worth")
        payload["total_pnl"] = summ.get("pnl", {}).get("total")
        payload["total_pct"] = summ.get("pnl", {}).get("total_pct")
        payload["day_pnl"] = summ.get("pnl", {}).get("holdings_day")
        day0 = _ist_day_start_utc(now_ist)
        fills_q = select(func.count(), func.coalesce(func.sum(PaperTrade.realized_pnl), 0.0)).where(
            PaperTrade.traded_at >= day0
        )
        open_q = select(func.count()).select_from(PaperPosition).where(
            PaperPosition.status == "OPEN", PaperPosition.net_qty != 0
        )
        if acct_id:
            fills_q = fills_q.where(PaperTrade.account_id == acct_id)
            open_q = open_q.where(PaperPosition.account_id == acct_id)
        n_fills, realized = db.execute(fills_q).one()
        payload["fills_today"] = int(n_fills)
        payload["realized_today"] = round(float(realized), 2)
        payload["open_positions"] = int(db.execute(open_q).scalar() or 0)
    except Exception:  # noqa: BLE001 - a partial summary still beats none
        logger.exception("daily_summary_paper_stats_failed")

    try:
        from app.market_scanner import service as ms_service

        recs = ms_service.recommendations(db)
        s = recs.get("summary", {})
        payload["ideas_live"] = s.get("live", 0)
        payload["ideas_target"] = s.get("target", 0)
        payload["ideas_sl"] = s.get("sl", 0)
        payload["ideas_neutral"] = s.get("neutral", 0)
    except Exception:  # noqa: BLE001
        logger.exception("daily_summary_scanner_stats_failed")

    enqueue(db, KIND_DAILY_SUMMARY, title=f"Paper account · {today}", body="", payload=payload)
    cfg.last_summary_day = today
    db.commit()
    return True


# --------------------------------------------------------------------------
# read side for the API
# --------------------------------------------------------------------------

def recent(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Notification).order_by(Notification.created_at.desc()).limit(min(limit, 200))
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "kind": r.kind,
            "title": r.title,
            "status": r.status,
            "attempts": r.attempts,
            "last_error": r.last_error,
        }
        for r in rows
    ]


def detect_chats(settings: Settings | None = None) -> list[dict[str, str]]:
    settings = settings or get_settings()
    if not settings.telegram_bot_token:
        return []
    return telegram.get_updates(settings.telegram_bot_token)
