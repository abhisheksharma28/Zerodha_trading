"""Zerodha broker connection lifecycle for this single-user platform.

Wraps app.brokers.zerodha.client.KiteClient + app.core.security to persist
the access token encrypted at rest, and never lets a raw token leave this
module (schemas.broker.BrokerStatus intentionally has no token field).
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.brokers.zerodha.client import KiteClient
from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.security import decrypt_secret, encrypt_secret
from app.models.audit import AuditLog  # noqa: F401 (re-exported for callers)
from app.models.broker_session import BrokerSession
from app.models.enums import AuditAction, ChangeEntityType
from app.repositories.broker_repository import BrokerSessionRepository


def get_login_url(settings: Settings) -> str:
    client = KiteClient(settings.zerodha_api_key, settings.zerodha_api_secret)
    return client.get_login_url()


def exchange_request_token(db: Session, settings: Settings, request_token: str) -> BrokerSession:
    client = KiteClient(settings.zerodha_api_key, settings.zerodha_api_secret)
    session_data = client.generate_session(request_token)

    row = BrokerSession(
        broker="zerodha",
        kite_user_id=session_data.kite_user_id,
        access_token_encrypted=encrypt_secret(session_data.access_token),
        public_token=session_data.public_token,
        connected_at=datetime.now(UTC),
        expires_at=session_data.expires_at,
    )
    db.add(row)

    record_audit(
        db,
        action=AuditAction.LOGIN,
        entity_type=ChangeEntityType.BROKER_SESSION,
        entity_id=row.id,
        summary=f"Connected Zerodha session for user {session_data.kite_user_id}",
        after={"kite_user_id": session_data.kite_user_id, "expires_at": str(session_data.expires_at)},
    )
    db.commit()
    db.refresh(row)
    return row


def get_status(db: Session) -> BrokerSession | None:
    repo = BrokerSessionRepository(db)
    latest = repo.get_latest()
    if latest is None or latest.invalidated_at is not None:
        return None
    if latest.expires_at and latest.expires_at < datetime.now(UTC):
        return None
    return latest


def build_authenticated_client(db: Session, settings: Settings) -> KiteClient:
    session = get_status(db)
    if session is None or session.access_token_encrypted is None:
        raise BrokerNotConnectedError(
            "No active Zerodha session. Complete the login flow via "
            "GET /api/v1/broker/login-url before deploying paper/live strategies."
        )
    access_token = decrypt_secret(session.access_token_encrypted)
    return KiteClient(settings.zerodha_api_key, settings.zerodha_api_secret, access_token)


def disconnect(db: Session) -> None:
    session = get_status(db)
    if session is None:
        return
    session.invalidated_at = datetime.now(UTC)
    record_audit(
        db,
        action=AuditAction.LOGOUT,
        entity_type=ChangeEntityType.BROKER_SESSION,
        entity_id=session.id,
        summary="Disconnected Zerodha session",
    )
    db.commit()
