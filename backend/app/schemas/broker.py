from datetime import datetime

from pydantic import BaseModel


class BrokerLoginUrl(BaseModel):
    login_url: str


class BrokerSessionExchange(BaseModel):
    request_token: str


class BrokerStatus(BaseModel):
    """Deliberately never includes access_token or any raw secret — see
    app.models.broker_session.BrokerSession docstring."""

    connected: bool
    broker: str = "zerodha"
    kite_user_id: str | None = None
    connected_at: datetime | None = None
    expires_at: datetime | None = None
