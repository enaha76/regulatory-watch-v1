"""
Frontend-shaped alert endpoints (`/api/v2/alerts`).

These mirror the M5 alerts router (`/api/alerts`) but reshape the payload to
match what the regwatch admin frontend expects. See app/services/alert_adapter.py
for the field-by-field mapping.

Two endpoints intentionally duplicate the v1 list/patch — keeping them
side-by-side means we can iterate the frontend contract without breaking
M5 consumers that already call /api/alerts.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models import Alert, ChangeEvent, UserSubscription
from app.services.alert_adapter import (
    build_frontend_alert,
    status_fe_to_be,
)


router = APIRouter(prefix="/api/v2/alerts", tags=["Frontend Alerts (v2)"])


# ── Request / query schemas ───────────────────────────────────────────

class AlertPatch(BaseModel):
    """
    PATCH body. All fields optional — the frontend can update any subset.

    `userFeedback` accepts an explicit `null` to clear a prior review
    (the Undo button) — pydantic distinguishes "field omitted" from
    "field set to null" via model_fields_set, which the handler uses.
    """
    status: Optional[str] = Field(
        default=None,
        pattern="^(new|read|archived)$",
        description="Frontend status — translated to DB vocabulary internally",
    )
    pinned: Optional[bool] = None
    userFeedback: Optional[str] = Field(
        default=None,
        pattern="^(relevant|not_relevant|partially_relevant)$",
    )


# ── Helpers ───────────────────────────────────────────────────────────

def _resolve_alert(session: Session, alert_id: UUID) -> tuple[Alert, ChangeEvent]:
    """Load an alert + its event, raising 404 if either is missing."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    event = session.get(ChangeEvent, alert.change_event_id)
    if event is None:
        # Orphaned alert — shouldn't happen with FK constraints, but be safe
        raise HTTPException(status_code=500, detail="Alert references missing event")
    return alert, event


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[dict])
def list_alerts_v2(
    email: Optional[str] = Query(
        default=None,
        description="Filter to one user's subscriptions. Omit to see every alert.",
    ),
    status: Optional[str] = Query(
        default=None,
        pattern="^(new|read|archived)$",
        description="Frontend status filter",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    List alerts shaped for the regwatch admin frontend.

    Most-recent first. If `email` is supplied, only that user's alerts
    are returned. Otherwise — useful for admin dashboards — every alert
    is included.

    Dedup: a single regulatory ChangeEvent typically matches multiple
    user subscriptions, generating one alert row per subscription. The
    admin view collapses these into one row per ChangeEvent so the
    inbox shows real changes, not subscription-fanout duplicates. The
    most-recent alert per event wins; pin/feedback state of the other
    matching alerts is preserved on those rows in the DB and surfaces
    if the user filters down to that subscription specifically.
    """
    stmt = select(Alert)

    if email:
        sub_ids = list(
            session.exec(
                select(UserSubscription.id).where(
                    UserSubscription.user_email == email
                )
            ).all()
        )
        if not sub_ids:
            return []
        stmt = stmt.where(Alert.subscription_id.in_(sub_ids))

    if status:
        stmt = stmt.where(Alert.status == status_fe_to_be(status))

    # Over-fetch so dedup doesn't starve us of rows. Cap the multiplier
    # so a pathological 100x-fanout doesn't blow up the query.
    overfetch = min(limit * 3, 1000)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(overfetch)

    out: list[dict] = []
    seen_event_ids: set = set()
    for alert in session.exec(stmt).all():
        if alert.change_event_id in seen_event_ids:
            continue
        seen_event_ids.add(alert.change_event_id)

        event = session.get(ChangeEvent, alert.change_event_id)
        if event is None:
            # Orphaned row — skip silently rather than crash the whole list
            continue
        out.append(build_frontend_alert(session, alert, event))
        if len(out) >= limit:
            break
    return out


@router.get("/{alert_id}", response_model=dict)
def get_alert_v2(
    alert_id: UUID,
    session: Session = Depends(get_session),
):
    """Single alert detail — adds a `summary` bullet array."""
    alert, event = _resolve_alert(session, alert_id)
    return build_frontend_alert(session, alert, event, include_summary_bullets=True)


@router.patch("/{alert_id}", response_model=dict)
def update_alert_v2(
    alert_id: UUID,
    body: AlertPatch,
    session: Session = Depends(get_session),
):
    """
    Update an alert. Translates frontend vocabulary → DB.

    Accepts:
      status        new | read | archived             (persisted)
      pinned        bool                              (persisted)
      userFeedback  string | null                     (persisted; null clears)
    """
    alert, event = _resolve_alert(session, alert_id)

    fields_set = body.model_fields_set
    dirty = False

    if "status" in fields_set and body.status is not None:
        alert.status = status_fe_to_be(body.status)
        dirty = True

    if "pinned" in fields_set and body.pinned is not None:
        alert.pinned = body.pinned
        dirty = True

    # userFeedback supports explicit null to clear (Undo button).
    if "userFeedback" in fields_set:
        alert.user_feedback = body.userFeedback
        dirty = True

    if dirty:
        session.add(alert)
        session.commit()
        session.refresh(alert)

    return build_frontend_alert(session, alert, event, include_summary_bullets=True)
