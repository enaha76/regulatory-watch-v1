"""
M5 Alert inbox endpoints.

- GET   /api/alerts              — list alerts for a user (with event details)
- PATCH /api/alerts/{id}         — mark as read / dismissed
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models import Alert, ChangeEvent, UserSubscription

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
    created_at: datetime
    event: AlertEventSummary


class AlertStatusUpdate(BaseModel):
    """PATCH body for updating alert status."""
    status: str = Field(
        ..., pattern="^(unread|read|dismissed)$",
        examples=["read"],
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AlertRead])
def list_alerts(
    email: str = Query(..., description="User email to filter by"),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status (unread, read, dismissed)",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    Fetch alerts for a user, joined with event details.

    Returns the most recent alerts first.
    """
    # First get all subscription IDs for this user.
    sub_stmt = select(UserSubscription.id).where(
        UserSubscription.user_email == email
    )
    sub_ids = [row for row in session.exec(sub_stmt).all()]

    if not sub_ids:
        return []

    # Build the alerts query.
    stmt = (
        select(Alert)
        .where(Alert.subscription_id.in_(sub_ids))
    )
    if status:
        stmt = stmt.where(Alert.status == status)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit)

    alerts = session.exec(stmt).all()

    # Hydrate with event and subscription data.
    results = []
    for alert in alerts:
        event = session.get(ChangeEvent, alert.change_event_id)
        sub = session.get(UserSubscription, alert.subscription_id)
        if not event or not sub:
            continue

        results.append(AlertRead(
            id=alert.id,
            subscription_id=alert.subscription_id,
            subscription_label=sub.label,
            change_event_id=alert.change_event_id,
            matched_keywords=alert.matched_keywords,
            status=alert.status,
            created_at=alert.created_at,
            event=AlertEventSummary(
                source_url=event.source_url,
                topic=event.topic,
                trade_flow_direction=event.trade_flow_direction,
                origin_countries=event.origin_countries,
                destination_countries=event.destination_countries,
                summary=event.summary,
                significance_score=event.significance_score,
                detected_at=event.detected_at,
            ),
        ))

    return results


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert_status(
    alert_id: UUID,
    body: AlertStatusUpdate,
    session: Session = Depends(get_session),
):
    """Mark an alert as read or dismissed."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = body.status
    session.add(alert)
    session.commit()
    session.refresh(alert)

    event = session.get(ChangeEvent, alert.change_event_id)
    sub = session.get(UserSubscription, alert.subscription_id)

    return AlertRead(
        id=alert.id,
        subscription_id=alert.subscription_id,
        subscription_label=sub.label if sub else "Unknown",
        change_event_id=alert.change_event_id,
        matched_keywords=alert.matched_keywords,
        status=alert.status,
        created_at=alert.created_at,
        event=AlertEventSummary(
            source_url=event.source_url,
            topic=event.topic,
            trade_flow_direction=event.trade_flow_direction,
            origin_countries=event.origin_countries,
            destination_countries=event.destination_countries,
            summary=event.summary,
            significance_score=event.significance_score,
            detected_at=event.detected_at,
        ) if event else None,
    )
