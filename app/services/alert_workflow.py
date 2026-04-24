"""
Alert workflow service — state machine, assignment, comments, audit log.

The module owns **every mutation** to an Alert's workflow state plus
the `alert_comments` / `alert_activity` tables. The HTTP router is a
thin adapter that validates input and calls into here. Centralising
the rules here means:

  * The state machine lives in ONE place; reviewers can read it in
    ten seconds.
  * Every action produces an audit row automatically — routers cannot
    "forget" to log.
  * Terminal-state invariants (``resolution_note`` required,
    ``closed_at`` set) are enforced alongside the transition, not
    sprinkled across endpoints.

Public API
----------
* ``transition(session, alert_id, new_status, actor, resolution_note=None)``
* ``assign(session, alert_id, assignee, actor)``
* ``unassign(session, alert_id, actor)``
* ``set_due_date(session, alert_id, due_date, actor)``
* ``add_comment(session, alert_id, author, body)``
* ``list_comments(session, alert_id)``
* ``list_activity(session, alert_id)``

All mutations raise ``WorkflowError`` on invalid input (bad
transition, missing resolution_note, alert not found, …). The caller
translates that into a 400 / 404.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.logging_setup import get_logger
from app.models import Alert, AlertActivity, AlertComment

log = get_logger(__name__)


# ── State machine ────────────────────────────────────────────────────────────

WORKFLOW_STATUSES = ("open", "in_progress", "done", "waived")
TERMINAL_STATUSES = {"done", "waived"}

# Allowed transitions. Terminal states have no outbound edges; a
# mistaken close requires a new alert (via re-scoring) or an explicit
# admin action — we don't want accidental reopen from the regular API.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open":        {"in_progress", "done", "waived"},
    "in_progress": {"open", "done", "waived"},
    "done":        set(),
    "waived":      set(),
}


class WorkflowError(ValueError):
    """Raised by the workflow service on invalid input.

    Carries a machine-readable ``code`` so the router can translate to
    the right HTTP status (400 vs 404 vs 409).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_alert_or_raise(session: Session, alert_id: UUID) -> Alert:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise WorkflowError("not_found", f"Alert {alert_id} not found")
    return alert


def _log_activity(
    session: Session,
    *,
    alert_id: UUID,
    actor_email: str,
    action: str,
    details: Optional[dict] = None,
) -> AlertActivity:
    row = AlertActivity(
        alert_id=alert_id,
        actor_email=actor_email,
        action=action,
        details=details,
    )
    session.add(row)
    return row


# ── Transitions ──────────────────────────────────────────────────────────────

def transition(
    session: Session,
    alert_id: UUID,
    *,
    new_status: str,
    actor: str,
    resolution_note: Optional[str] = None,
) -> Alert:
    """
    Move an alert to ``new_status``.

    Validation:
      * ``new_status`` must be a known workflow status.
      * The transition ``current → new_status`` must be allowed.
      * Terminal transitions (``done``/``waived``) require a non-empty
        ``resolution_note``; the service persists it AND sets
        ``closed_at``. This mirrors the DB CHECK constraint so invalid
        states can't be reached via any path.

    Writes an ``AlertActivity`` row describing the transition.
    """
    if new_status not in WORKFLOW_STATUSES:
        raise WorkflowError(
            "bad_status",
            f"workflow_status must be one of {WORKFLOW_STATUSES}",
        )

    alert = _get_alert_or_raise(session, alert_id)
    current = alert.workflow_status

    if new_status == current:
        # No-op: idempotent, but we don't log it. Prevents noisy audit
        # trails when the UI triple-clicks the same button.
        return alert

    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise WorkflowError(
            "invalid_transition",
            f"cannot transition from {current!r} to {new_status!r}",
        )

    if new_status in TERMINAL_STATUSES:
        note = (resolution_note or "").strip()
        if not note:
            raise WorkflowError(
                "missing_resolution_note",
                f"resolution_note is required when closing to {new_status!r}",
            )
        alert.resolution_note = note
        alert.closed_at = _utcnow()
    else:
        # Non-terminal: make sure closed_at is cleared if we were
        # somehow set previously. Shouldn't happen given the state
        # machine, but defensive against direct DB edits.
        alert.closed_at = None

    prev_status = alert.workflow_status
    alert.workflow_status = new_status
    session.add(alert)

    _log_activity(
        session,
        alert_id=alert_id,
        actor_email=actor,
        action="status_changed",
        details={
            "from": prev_status,
            "to": new_status,
            **({"resolution_note": alert.resolution_note} if new_status in TERMINAL_STATUSES else {}),
        },
    )
    log.info(
        "alert_workflow_transition",
        alert_id=str(alert_id),
        from_status=prev_status,
        to_status=new_status,
        actor=actor,
    )
    return alert


# ── Assignment ───────────────────────────────────────────────────────────────

def assign(
    session: Session,
    alert_id: UUID,
    *,
    assignee: str,
    actor: str,
) -> Alert:
    """Assign an alert to ``assignee``. ``actor`` is who did the assigning."""
    assignee = (assignee or "").strip()
    if not assignee:
        raise WorkflowError(
            "missing_assignee",
            "assignee email is required; use /unassign to clear",
        )

    alert = _get_alert_or_raise(session, alert_id)
    prev = alert.assigned_to

    alert.assigned_to = assignee
    alert.assigned_by = actor
    alert.assigned_at = _utcnow()
    session.add(alert)

    _log_activity(
        session,
        alert_id=alert_id,
        actor_email=actor,
        action="assigned",
        details={"from": prev, "to": assignee},
    )
    log.info(
        "alert_assigned",
        alert_id=str(alert_id),
        assignee=assignee,
        previous=prev,
        actor=actor,
    )
    return alert


def unassign(session: Session, alert_id: UUID, *, actor: str) -> Alert:
    """Clear the assignment. No-op if already unassigned."""
    alert = _get_alert_or_raise(session, alert_id)
    if alert.assigned_to is None:
        return alert

    prev = alert.assigned_to
    alert.assigned_to = None
    alert.assigned_by = None
    alert.assigned_at = None
    session.add(alert)

    _log_activity(
        session,
        alert_id=alert_id,
        actor_email=actor,
        action="unassigned",
        details={"from": prev},
    )
    log.info("alert_unassigned", alert_id=str(alert_id), previous=prev, actor=actor)
    return alert


# ── Due date ─────────────────────────────────────────────────────────────────

def set_due_date(
    session: Session,
    alert_id: UUID,
    *,
    due_date: Optional[date],
    actor: str,
) -> Alert:
    """Set or clear (pass None) the due date."""
    alert = _get_alert_or_raise(session, alert_id)
    prev = alert.due_date
    if prev == due_date:
        return alert

    alert.due_date = due_date
    session.add(alert)

    _log_activity(
        session,
        alert_id=alert_id,
        actor_email=actor,
        action="due_date_changed",
        details={
            "from": prev.isoformat() if prev else None,
            "to": due_date.isoformat() if due_date else None,
        },
    )
    return alert


# ── Comments ─────────────────────────────────────────────────────────────────

def add_comment(
    session: Session,
    alert_id: UUID,
    *,
    author: str,
    body: str,
) -> AlertComment:
    """Append a comment. Records an activity row with a short preview."""
    body_clean = (body or "").strip()
    if not body_clean:
        raise WorkflowError("empty_comment", "comment body cannot be empty")

    # Validate the alert exists before writing the comment.
    _get_alert_or_raise(session, alert_id)

    comment = AlertComment(
        alert_id=alert_id,
        author_email=author,
        body=body_clean,
    )
    session.add(comment)
    session.flush()  # get comment.id for the activity row

    # Keep the activity preview short so ``list_activity`` stays scannable.
    preview = body_clean[:140] + ("…" if len(body_clean) > 140 else "")
    _log_activity(
        session,
        alert_id=alert_id,
        actor_email=author,
        action="commented",
        details={"comment_id": str(comment.id), "preview": preview},
    )
    return comment


def list_comments(
    session: Session,
    alert_id: UUID,
) -> list[AlertComment]:
    """Oldest-first, matching how a threaded view renders them."""
    _get_alert_or_raise(session, alert_id)
    stmt = (
        select(AlertComment)
        .where(AlertComment.alert_id == alert_id)
        .order_by(AlertComment.created_at)
    )
    return list(session.exec(stmt).all())


# ── Activity log ─────────────────────────────────────────────────────────────

def list_activity(
    session: Session,
    alert_id: UUID,
    *,
    limit: int = 200,
) -> list[AlertActivity]:
    """Newest-first — most UIs render audit trails top-down from latest."""
    _get_alert_or_raise(session, alert_id)
    stmt = (
        select(AlertActivity)
        .where(AlertActivity.alert_id == alert_id)
        .order_by(AlertActivity.created_at.desc())
        .limit(limit)
    )
    return list(session.exec(stmt).all())
