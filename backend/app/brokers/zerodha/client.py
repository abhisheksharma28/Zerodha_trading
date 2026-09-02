"""Kite Connect REST client.

Every call goes through `_request`, which applies per-endpoint-class rate
limiting (see app.risk.limiter — quote/historical/order buckets are
independent per docs/ZERODHA_API_NOTES.md section 4), translates Kite's JSON
error envelope into typed exceptions, and retries only on 429/5xx — never on
a 4xx order rejection, which is terminal and must surface to the caller (and
from there, the audit log) untouched.
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.brokers.base import BrokerSessionData, OrderRequest, PlacedOrderResult
from app.brokers.exceptions import (
    NetworkException,
    RateLimitExceeded,
    exception_from_kite_response,
)
from app.brokers.zerodha.auth import KITE_API_BASE, build_checksum, build_login_url
from app.brokers.zerodha.order_builder import build_order_payload
from app.core.logging import get_logger
from app.risk.limiter import RateLimiter

logger = get_logger(__name__)

_KITE_VERSION = "3"

# Kite's per-request date-range ceiling by interval (days). Larger spans are
# fetched page-by-page and stitched — see get_historical_candles.
_KITE_HIST_MAX_DAYS: dict[str, int] = {
    "minute": 55,
    "3minute": 85,
    "5minute": 90,
    "10minute": 90,
    "15minute": 180,
    "30minute": 180,
    "60minute": 360,
    "day": 1900,
}


class KiteClient:
    """Thin, typed wrapper over the Kite Connect v3 REST API.

    Deliberately does NOT know about TradingMode, deployments, or the
    execution guard — see app.execution.guard / app.execution.router for
    where the "is this call even allowed" decision is made. This class's
    only job is "talk to Kite correctly and safely once we've already
    decided to."
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str | None = None,
        *,
        base_url: str = KITE_API_BASE,
        timeout: float = 7.0,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.base_url = base_url
        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._order_limiter = RateLimiter.for_orders()
        self._quote_limiter = RateLimiter.for_quotes()
        self._historical_limiter = RateLimiter.for_historical()

    # --- Auth -------------------------------------------------------------

    def get_login_url(self) -> str:
        return build_login_url(self.api_key)

    def generate_session(self, request_token: str) -> BrokerSessionData:
        checksum = build_checksum(self.api_key, request_token, self.api_secret)
        resp = self._raw_request(
            "POST",
            "/session/token",
            data={
                "api_key": self.api_key,
                "request_token": request_token,
                "checksum": checksum,
            },
            authenticated=False,
        )
        data = resp["data"]
        self.access_token = data["access_token"]
        return BrokerSessionData(
            access_token=data["access_token"],
            public_token=data.get("public_token"),
            kite_user_id=data.get("user_id"),
            expires_at=_next_six_am_ist(),
        )

    def invalidate_session(self) -> None:
        self._raw_request(
            "DELETE",
            "/session/token",
            params={"api_key": self.api_key, "access_token": self.access_token},
        )
        self.access_token = None

    # --- Orders -------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> PlacedOrderResult:
        payload = build_order_payload(order)
        self._order_limiter.acquire()
        resp = self._raw_request(
            "POST", f"/orders/{order.variety}", data=payload
        )
        return PlacedOrderResult(
            broker_order_id=resp["data"]["order_id"], raw_response=resp
        )

    def cancel_order(self, broker_order_id: str, *, variety: str = "regular") -> None:
        self._order_limiter.acquire()
        self._raw_request("DELETE", f"/orders/{variety}/{broker_order_id}")

    def get_orders(self) -> list[dict[str, Any]]:
        return self._raw_request("GET", "/orders")["data"]

    def get_trades(self) -> list[dict[str, Any]]:
        return self._raw_request("GET", "/trades")["data"]

    # --- Portfolio / margins -------------------------------------------------

    def get_positions(self) -> dict[str, Any]:
        return self._raw_request("GET", "/portfolio/positions")["data"]

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._raw_request("GET", "/portfolio/holdings")["data"]

    def get_margins(self) -> dict[str, Any]:
        return self._raw_request("GET", "/user/margins")["data"]

    def get_profile(self) -> dict[str, Any]:
        return self._raw_request("GET", "/user/profile")["data"]

    # --- Market data ---------------------------------------------------------

    def get_quote(self, instruments: list[str]) -> dict[str, Any]:
        self._quote_limiter.acquire()
        return self._raw_request("GET", "/quote", params={"i": instruments})["data"]

    def get_historical_candles(
        self, instrument_token: str, interval: str, from_dt: datetime, to_dt: datetime,
        *, continuous: bool = False, oi: bool = False,
    ) -> list[list[Any]]:
        """Full OHLCV history for any date range. Kite caps a single request's
        span per interval, so ranges larger than that are fetched in
        successive pages and stitched — there is no cap on how far back the
        caller can ask for."""
        max_days = _KITE_HIST_MAX_DAYS.get(interval, 90)
        if (to_dt - from_dt).days <= max_days:
            return self._historical_page(instrument_token, interval, from_dt, to_dt, continuous, oi)

        out: list[list[Any]] = []
        step = timedelta(days=max_days)
        cur = from_dt
        while cur < to_dt:
            end = min(cur + step, to_dt)
            for c in self._historical_page(instrument_token, interval, cur, end, continuous, oi):
                # consecutive pages overlap by one candle at `end`; keep only
                # strictly-newer rows (Kite timestamps are ISO, sortable as text)
                if not out or str(c[0]) > str(out[-1][0]):
                    out.append(c)
            cur = end
        return out

    def _historical_page(
        self, instrument_token: str, interval: str, from_dt: datetime, to_dt: datetime,
        continuous: bool, oi: bool,
    ) -> list[list[Any]]:
        self._historical_limiter.acquire()
        params = {
            "from": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "to": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "continuous": 1 if continuous else 0,
            "oi": 1 if oi else 0,
        }
        resp = self._raw_request(
            "GET", f"/instruments/historical/{instrument_token}/{interval}", params=params
        )
        return resp["data"]["candles"]

    # --- Internals -------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((RateLimitExceeded, NetworkException)),
        wait=wait_exponential_jitter(initial=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        authenticated: bool = True,
    ) -> dict:
        headers = {"X-Kite-Version": _KITE_VERSION}
        if authenticated:
            if not self.access_token:
                from app.core.exceptions import BrokerAuthExpiredError

                raise BrokerAuthExpiredError("No active broker session — reconnect to Zerodha.")
            headers["Authorization"] = f"token {self.api_key}:{self.access_token}"

        try:
            resp = self._http.request(method, path, params=params, data=data, headers=headers)
        except httpx.RequestError as exc:
            raise NetworkException(f"Could not reach Kite Connect: {exc}") from exc

        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"error_type": "GeneralException", "message": resp.text}
            error = exception_from_kite_response(resp.status_code, body)
            logger.warning(
                "kite_api_error",
                method=method,
                path=path,
                status=resp.status_code,
                error_type=type(error).__name__,
            )
            raise error

        return resp.json()

    def close(self) -> None:
        self._http.close()


def _next_six_am_ist() -> datetime:
    """Kite access tokens expire at 6 AM IST the next calendar day
    (regulatory requirement, see docs/ZERODHA_API_NOTES.md section 1) — used
    only as a display/scheduling hint, never trusted over an actual 403 from
    the API."""
    from datetime import timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    next_day = now.date() + timedelta(days=1)
    return datetime(next_day.year, next_day.month, next_day.day, 6, 0, 0, tzinfo=ist)
