"""Broker-side exception taxonomy.

Mirrors Kite Connect's own exception names (see docs/ZERODHA_API_NOTES.md
section 4) so error handling can be broker-agnostic in the rest of the app —
a future second broker integration maps its own errors onto these same
classes.
"""


class BrokerError(Exception):
    def __init__(self, message: str, *, http_status: int | None = None, raw: dict | None = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.raw = raw or {}


class TokenException(BrokerError):
    """Session expired or invalid — caller must re-authenticate."""


class UserException(BrokerError):
    pass


class OrderException(BrokerError):
    pass


class InputException(BrokerError):
    pass


class MarginException(BrokerError):
    pass


class HoldingException(BrokerError):
    pass


class NetworkException(BrokerError):
    pass


class DataException(BrokerError):
    pass


class RateLimitExceeded(BrokerError):
    """Maps to Kite's 429."""


class GeneralException(BrokerError):
    pass


_EXCEPTION_NAME_MAP: dict[str, type[BrokerError]] = {
    "TokenException": TokenException,
    "UserException": UserException,
    "OrderException": OrderException,
    "InputException": InputException,
    "MarginException": MarginException,
    "HoldingException": HoldingException,
    "NetworkException": NetworkException,
    "DataException": DataException,
    "GeneralException": GeneralException,
}


def exception_from_kite_response(status_code: int, body: dict) -> BrokerError:
    """Translate a Kite Connect JSON error body into a typed BrokerError."""
    error_type = body.get("error_type", "GeneralException")
    message = body.get("message", "Unknown broker error")
    if status_code == 429:
        return RateLimitExceeded(message, http_status=status_code, raw=body)
    exc_cls = _EXCEPTION_NAME_MAP.get(error_type, GeneralException)
    return exc_cls(message, http_status=status_code, raw=body)
