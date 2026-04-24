"""
M5b alert delivery — pluggable notifier channels.

A notifier takes a resolved `(Alert, ChangeEvent, UserSubscription)`
tuple and pushes it to an external channel. Channels today:

  * email   — SMTP (stdlib smtplib, any relay)
  * none    — inbox-only (GET /api/alerts only)

Slack and generic webhook are intentionally stubbed so the
`Notifier` protocol and the Celery deliver_alert task can land
together; a follow-up PR fills them in.

Failure semantics
-----------------
A notifier raises ``NotifierError`` on any delivery failure. The
Celery deliver_alert task catches it, records the error on the Alert
row, and retries with exponential backoff up to
``DELIVER_ALERT_MAX_RETRIES``. Persistent failure dead-letters the
alert (stays undelivered, visible via the pending-delivery partial
index).
"""

from app.services.notifiers.base import Notifier, NotifierError
from app.services.notifiers.registry import get_notifier

__all__ = ["Notifier", "NotifierError", "get_notifier"]
