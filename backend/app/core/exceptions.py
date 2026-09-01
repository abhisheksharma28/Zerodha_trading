"""Application-wide exception hierarchy.

Kept distinct from `app.brokers.zerodha.exceptions` (which mirrors Kite's own
exception taxonomy) so the rest of the app never has to know which broker is
in use to handle an error sensibly.
"""


class AppError(Exception):
    """Base class for all application-raised errors."""

    http_status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    http_status = 404
    code = "not_found"


class ValidationError(AppError):
    http_status = 422
    code = "validation_error"


class ConflictError(AppError):
    http_status = 409
    code = "conflict"


class BrokerNotConnectedError(AppError):
    http_status = 409
    code = "broker_not_connected"


class BrokerAuthExpiredError(AppError):
    http_status = 409
    code = "broker_auth_expired"


class RiskLimitExceededError(AppError):
    """Raised by the risk layer; the execution layer must never catch and
    silently swallow this — it always aborts the order and logs an audit
    event."""

    http_status = 409
    code = "risk_limit_exceeded"


class UnsafeModeTransitionError(AppError):
    """Raised whenever code attempts to send a live order without the strategy
    being explicitly, currently deployed in LIVE mode. This exception must
    never be caught anywhere except the top-level API error handler and the
    audit logger — see app.execution.guard."""

    http_status = 403
    code = "unsafe_mode_transition"
