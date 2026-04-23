"""
M5 Subscription management endpoints.

- POST   /api/subscriptions          — create a new subscription
- GET    /api/subscriptions           — list subscriptions for a user
- PATCH  /api/subscriptions/{id}      — update a subscription
- DELETE /api/subscriptions/{id}      — delete a subscription
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models import UserSubscription

router = APIRouter(prefix="/api/subscriptions", tags=["M5 Subscriptions"])


# ── Request / Response schemas ───────────────────────────────────────────────

class SubscriptionCreate(BaseModel):
    """POST body for creating a subscription."""
    user_email: str = Field(..., min_length=3, max_length=255,
                            examples=["sarah@acme.com"])
    label: str = Field(default="Default Subscription", max_length=255,
                       examples=["My China Sanctions Watch"])
    topics: Optional[list[str]] = Field(
        default=None,
        examples=[["sanctions_export_control", "customs_trade"]],
    )
    origin_countries: Optional[list[str]] = Field(
        default=None, examples=[["US", "CN"]],
    )
    destination_countries: Optional[list[str]] = Field(
        default=None, examples=[["RU"]],
    )
    min_significance: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_query: Optional[str] = Field(
        default=None,
        examples=["lithium & batteri:*"],
        description="PostgreSQL tsquery string for full-text matching.",
    )


class SubscriptionUpdate(BaseModel):
    """PATCH body — all fields optional."""
    label: Optional[str] = None
    topics: Optional[list[str]] = None
    origin_countries: Optional[list[str]] = None
    destination_countries: Optional[list[str]] = None
    min_significance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    keyword_query: Optional[str] = None
    is_active: Optional[bool] = None


class SubscriptionRead(BaseModel):
    """Response schema."""
    id: UUID
    user_email: str
    label: str
    topics: Optional[list[str]]
    origin_countries: Optional[list[str]]
    destination_countries: Optional[list[str]]
    min_significance: float
    keyword_query: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=SubscriptionRead, status_code=201)
def create_subscription(
    body: SubscriptionCreate,
    session: Session = Depends(get_session),
):
    """Create a new alerting subscription."""
    sub = UserSubscription(**body.model_dump())
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(
    email: str = Query(..., description="User email to filter by"),
    session: Session = Depends(get_session),
):
    """List all subscriptions for a given user email."""
    stmt = (
        select(UserSubscription)
        .where(UserSubscription.user_email == email)
        .order_by(UserSubscription.created_at.desc())
    )
    return session.exec(stmt).all()


@router.patch("/{subscription_id}", response_model=SubscriptionRead)
def update_subscription(
    subscription_id: UUID,
    body: SubscriptionUpdate,
    session: Session = Depends(get_session),
):
    """Update an existing subscription (toggle active, change keywords, etc.)."""
    sub = session.get(UserSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(sub, key, value)
    sub.updated_at = datetime.now(timezone.utc)

    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@router.delete("/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: UUID,
    session: Session = Depends(get_session),
):
    """Delete a subscription and all its alerts."""
    sub = session.get(UserSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Delete related alerts first (no cascade defined in model).
    from app.models import Alert
    stmt = select(Alert).where(Alert.subscription_id == subscription_id)
    for alert in session.exec(stmt).all():
        session.delete(alert)

    session.delete(sub)
    session.commit()
