"""
Notifier protocol and shared error type.

A Notifier is a thin adapter: take an alert + its context, push it to
an external channel, raise ``NotifierError`` on failure. Zero DB,
zero Celery, zero awareness of retry policy — those belong to the
caller (the deliver_alert task).
"""

from __future__ import annotations

from typing import Protocol

from app.models import Alert, ChangeEvent, UserSubscription


class NotifierError(RuntimeError):
    """Raised by a Notifier when delivery fails.

    The caller is responsible for retry / backoff / dead-letter
    decisions. Keep the message short and safe-to-log (no raw secrets).
    """


class Notifier(Protocol):
    """Delivery channel adapter."""

    channel: str  # "email" | "slack" | "webhook" | "none"

    def send(
        self,
        *,
        alert: Alert,
        event: ChangeEvent,
        subscription: UserSubscription,
    ) -> None:
        """Push the alert to the channel. Raise NotifierError on failure."""
        ...
