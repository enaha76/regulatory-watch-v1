"""
M5 Alert inbox + workflow endpoints.

Inbox (visibility):
- GET   /api/alerts                          — list alerts for a user
- PATCH /api/alerts/{id}                     — mark as read / dismissed

Workflow (collaboration):
- PATCH /api/alerts/{id}/workflow            — transition status
- PATCH /api/alerts/{id}/assignment          — assign / unassign / due date
- POST  /api/alerts/{id}/comments            — add a comment
- GET   /api/alerts/{id}/comments            — list comments
- GET   /api/alerts/{id}/activity            — audit trail
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models import Alert, AlertActivity, AlertComment, ChangeEvent, UserSubscription
from app.services import alert_workflow
from app.services.alert_workflow import WorkflowError

router = APIRouter(prefix="/api/alerts", tags=["M5 Alerts"])


# ── Response schemas ─────────────────────────────────────────────────────────

class AlertEventSummary(BaseModel):
    """Nested event data embedded in the alert response."""
    source_url: str
    topic: Optional[str]
    trade_flow_direction: Optional[str]
    origin_countries: Optional[list[str]]
    destination_countries: Optional[list[str]]
    summary: Optional[str]
    significance_score: Optional[float]
    detected_at: datetime


class AlertRead(BaseModel):
    """Full alert response including the matched event details."""
    id: UUID
    subscription_id: UUID
    subscription_label: str
    change_event_id: UUID
    matched_keywords: Optional[list]
    status: str
    # Workflow fields (M5d)
    workflow_status: str
    assigned_to: Optional[str]
    assigned_by: Optional[str]
    assigned_at: Optional[datetime]
    due_date: Optional[date]
    resolution_note: Optional[str]
    closed_at: Optional[datetime]
    created_at: datetime
    event: Optional[AlertEventSummary]


class AlertStatusUpdate(BaseModel):
    """PATCH body for updating inbox status (unread/read/dismissed)."""
    status: str = Field(
        ..., pattern="^(unread|read|dismissed)$",
        examples=["read"],
    )


# ── Workflow request/response schemas (M5d) ──────────────────────────────────

class WorkflowTransitionBody(BaseModel):
    """PATCH /api/alerts/{id}/workflow."""
    workflow_status: str = Field(
        ..., pattern="^(open|in_progress|done|waived)$",
        examples=["in_progress"],
    )
    actor_email: str = Field(..., min_length=3, max_length=255)
    resolution_note: Optional[str] = Field(
        default=None, max_length=4000,
        description="Required when transitioning to 'done' or 'waived'.",
    )


class AssignmentBody(BaseModel):
    """PATCH /api/alerts/{id}/assignment.

    One call covers assign / unassign / due-date change. Any combination
    of fields is allowed; unsent fields are untouched. Set
    ``assignee_email=""`` to explicitly unassign.
    """
    assignee_email: Optional[str] = Field(
        default=None, max_length=255,
        description='Email of the new assignee. Empty string ("") unassigns.',
    )
    due_date: Optional[date] = Field(
        default=None,
        description="Optional deadline. Send null in JSON to leave unchanged.",
    )
    clear_due_date: bool = Field(
        default=False,
        description="Set true to explicitly clear the due_date.",
    )
    actor_email: str = Field(..., min_length=3, max_length=255)


class CommentCreate(BaseModel):
    author_email: str = Field(..., min_length=3, max_length=255)
    body: str = Field(..., min_length=1, max_length=10000)


class CommentRead(BaseModel):
    id: UUID
    alert_id: UUID
    author_email: str
    body: str
    created_at: datetime


class ActivityRead(BaseModel):
    id: UUID
    alert_id: UUID
    actor_email: str
    action: str
    details: Optional[dict]
    created_at: datetime


# ── Error mapping ────────────────────────────────────────────────────────────

_WORKFLOW_ERROR_STATUS = {
    "not_found": 404,
    "bad_status": 400,
    "invalid_transition": 409,
    "missing_resolution_note": 400,
    "missing_assignee": 400,
    "empty_comment": 400,
}


def _raise_from_workflow(exc: WorkflowError) -> None:
    raise HTTPException(
        status_code=_WORKFLOW_ERROR_STATUS.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


def _alert_to_read(alert: Alert, session: Session) -> AlertRead:
    """Hydrate an Alert with its subscription label + event summary."""
    sub = session.get(UserSubscription, alert.subscription_id)
    event = session.get(ChangeEvent, alert.change_event_id)
    event_summary = None
    if event is not None:
        event_summary = AlertEventSummary(
            source_url=event.source_url,
            topic=event.topic,
            trade_flow_direction=event.trade_flow_direction,
            origin_countries=event.origin_countries,
            destination_countries=event.destination_countries,
            summary=event.summary,
            significance_score=event.significance_score,
            detected_at=event.detected_at,
        )
    return AlertRead(
        id=alert.id,
        subscription_id=alert.subscription_id,
        subscription_label=sub.label if sub else "Unknown",
        change_event_id=alert.change_event_id,
        matched_keywords=alert.matched_keywords,
        status=alert.status,
        workflow_status=alert.workflow_status,
        assigned_to=alert.assigned_to,
        assigned_by=alert.assigned_by,
        assigned_at=alert.assigned_at,
        due_date=alert.due_date,
        resolution_note=alert.resolution_note,
        closed_at=alert.closed_at,
        created_at=alert.created_at,
        event=event_summary,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AlertRead])
def list_alerts(
    email: str = Query(..., description="User email to filter by"),
    status: Optional[str] = Query(
        default=None,
        description="Filter by inbox status (unread, read, dismissed)",
    ),
    workflow_status: Optional[str] = Query(
        default=None,
        description="Filter by workflow status (open, in_progress, done, waived)",
    ),
    assigned_to: Optional[str] = Query(
        default=None,
        description="Filter to alerts assigned to this email.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    Fetch alerts for a user, joined with event details.

    Returns the most recent alerts first. Workflow filters let a team
    lead pull "open & unassigned", "in_progress assigned to me", etc.
    """
    sub_stmt = select(UserSubscription.id).where(
        UserSubscription.user_email == email
    )
    sub_ids = [row for row in session.exec(sub_stmt).all()]
    if not sub_ids:
        return []

    stmt = select(Alert).where(Alert.subscription_id.in_(sub_ids))
    if status:
        stmt = stmt.where(Alert.status == status)
    if workflow_status:
        stmt = stmt.where(Alert.workflow_status == workflow_status)
    if assigned_to:
        stmt = stmt.where(Alert.assigned_to == assigned_to)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit)

    alerts = session.exec(stmt).all()
    return [_alert_to_read(a, session) for a in alerts]


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert_status(
    alert_id: UUID,
    body: AlertStatusUpdate,
    session: Session = Depends(get_session),
):
    """Mark an alert's inbox status (unread / read / dismissed)."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = body.status
    session.add(alert)
    session.commit()
    session.refresh(alert)

    return _alert_to_read(alert, session)


# ── Workflow endpoints (M5d) ─────────────────────────────────────────────────

@router.patch("/{alert_id}/workflow", response_model=AlertRead)
def transition_workflow(
    alert_id: UUID,
    body: WorkflowTransitionBody,
    session: Session = Depends(get_session),
):
    """
    Transition an alert's workflow_status.

    Validated against the state machine in alert_workflow.
    Closing to 'done' / 'waived' requires ``resolution_note``.
    """
    try:
        alert = alert_workflow.transition(
            session, alert_id,
            new_status=body.workflow_status,
            actor=body.actor_email,
            resolution_note=body.resolution_note,
        )
    except WorkflowError as exc:
        _raise_from_workflow(exc)
    session.commit()
    session.refresh(alert)
    return _alert_to_read(alert, session)


@router.patch("/{alert_id}/assignment", response_model=AlertRead)
def update_assignment(
    alert_id: UUID,
    body: AssignmentBody,
    session: Session = Depends(get_session),
):
    """
    Assign / unassign the alert and/or change its due_date.

    - ``assignee_email`` == ``""`` (empty string) → unassign
    - ``assignee_email`` == null (omitted) → leave untouched
    - ``due_date`` + ``clear_due_date=true`` → clear the due date
    """
    try:
        if body.assignee_email is not None:
            if body.assignee_email.strip() == "":
                alert = alert_workflow.unassign(
                    session, alert_id, actor=body.actor_email,
                )
            else:
                alert = alert_workflow.assign(
                    session, alert_id,
                    assignee=body.assignee_email,
                    actor=body.actor_email,
                )
        else:
            alert = alert_workflow._get_alert_or_raise(session, alert_id)

        if body.clear_due_date:
            alert = alert_workflow.set_due_date(
                session, alert_id, due_date=None, actor=body.actor_email,
            )
        elif body.due_date is not None:
            alert = alert_workflow.set_due_date(
                session, alert_id, due_date=body.due_date, actor=body.actor_email,
            )
    except WorkflowError as exc:
        _raise_from_workflow(exc)

    session.commit()
    session.refresh(alert)
    return _alert_to_read(alert, session)


@router.post("/{alert_id}/comments",
             response_model=CommentRead, status_code=201)
def post_comment(
    alert_id: UUID,
    body: CommentCreate,
    session: Session = Depends(get_session),
):
    """Append a comment to an alert's discussion thread."""
    try:
        comment = alert_workflow.add_comment(
            session, alert_id,
            author=body.author_email,
            body=body.body,
        )
    except WorkflowError as exc:
        _raise_from_workflow(exc)
    session.commit()
    session.refresh(comment)
    return CommentRead(
        id=comment.id,
        alert_id=comment.alert_id,
        author_email=comment.author_email,
        body=comment.body,
        created_at=comment.created_at,
    )


@router.get("/{alert_id}/comments", response_model=list[CommentRead])
def list_comments(
    alert_id: UUID,
    session: Session = Depends(get_session),
):
    """Oldest-first list of comments on this alert."""
    try:
        comments = alert_workflow.list_comments(session, alert_id)
    except WorkflowError as exc:
        _raise_from_workflow(exc)
    return [
        CommentRead(
            id=c.id, alert_id=c.alert_id,
            author_email=c.author_email, body=c.body,
            created_at=c.created_at,
        )
        for c in comments
    ]


@router.get("/{alert_id}/activity", response_model=list[ActivityRead])
def list_activity(
    alert_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """Newest-first audit trail: assignments, status changes, comments."""
    try:
        rows = alert_workflow.list_activity(session, alert_id, limit=limit)
    except WorkflowError as exc:
        _raise_from_workflow(exc)
    return [
        ActivityRead(
            id=r.id, alert_id=r.alert_id,
            actor_email=r.actor_email, action=r.action,
            details=r.details, created_at=r.created_at,
        )
        for r in rows
    ]
