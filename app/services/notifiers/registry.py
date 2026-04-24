"""
Channel → Notifier registry.

Dispatches a subscription's ``channel`` string to the right Notifier
instance. New channels land here as one-line additions once their
implementation module exists.
"""

from __future__ import annotations

from typing import Optional

from app.services.notifiers.base import Notifier, NotifierError
from app.services.notifiers.email import EmailNotifier


# Singleton notifiers — they're stateless enough to share across
# Celery task invocations.
_EMAIL = EmailNotifier()


def get_notifier(channel: str) -> Optional[Notifier]:
    """Return the Notifier for ``channel`` or None for inbox-only subscriptions.

    Raises NotifierError for a channel that's declared but unimplemented
    (e.g. slack before we ship it) — the caller should record the error
    on the alert and NOT retry forever.
    """
    ch = (channel or "").strip().lower()
    if ch in ("", "none"):
        return None
    if ch == "email":
        return _EMAIL
    if ch in ("slack", "webhook"):
        raise NotifierError(f"channel '{ch}' not implemented yet")
    raise NotifierError(f"unknown channel '{channel}'")
