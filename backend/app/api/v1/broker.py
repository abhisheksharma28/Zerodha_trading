from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.schemas.broker import BrokerLoginUrl, BrokerSessionExchange, BrokerStatus
from app.services import broker_service

router = APIRouter(prefix="/broker", tags=["broker"])


@router.get("/login-url", response_model=BrokerLoginUrl)
def login_url(settings: Settings = Depends(get_settings)):
    return BrokerLoginUrl(login_url=broker_service.get_login_url(settings))


@router.post("/session", response_model=BrokerStatus)
def exchange_session(
    payload: BrokerSessionExchange,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    session = broker_service.exchange_request_token(db, settings, payload.request_token)
    return BrokerStatus(
        connected=True,
        kite_user_id=session.kite_user_id,
        connected_at=session.connected_at,
        expires_at=session.expires_at,
    )


@router.get("/status", response_model=BrokerStatus)
def status(db: Session = Depends(get_db)):
    session = broker_service.get_status(db)
    if session is None:
        return BrokerStatus(connected=False)
    return BrokerStatus(
        connected=True,
        kite_user_id=session.kite_user_id,
        connected_at=session.connected_at,
        expires_at=session.expires_at,
    )


@router.post("/disconnect", status_code=204)
def disconnect(db: Session = Depends(get_db)):
    broker_service.disconnect(db)
