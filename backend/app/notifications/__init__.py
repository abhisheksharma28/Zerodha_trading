"""Outbound notifications - push trade activity to the user's phone via Telegram.

Isolated package. Two things get pushed:

* **Market Scanner ideas** - each new LIVE recommendation as it fires
  (grade-filtered), plus the outcome when a tracked idea resolves.
* **Paper trading account** - every order fill, plus one wrap-up message
  after the close.

Design: an **outbox**. Event sites call :func:`app.notifications.service.enqueue`
- a plain INSERT on their existing transaction, no network. A background
loop (:mod:`app.notifications.scheduler`) delivers ``pending`` rows to
Telegram and marks them ``sent`` / ``failed``. So Telegram being slow or
down can never block or crash the scanner / tracker / order path.

The bot token is the only secret (``settings.telegram_bot_token``); the
chat id and every toggle live in the ``notification_config`` DB row and are
edited from Settings ▸ Notifications. Empty token => dormant: rows are
recorded ``skipped`` and nothing is sent.
"""

from app.notifications.service import enqueue

__all__ = ["enqueue"]
