"""
M5 Subscription management endpoints.

- POST   /api/subscriptions          — create a new subscription
- GET    /api/subscriptions           — list subscriptions for a user
- PATCH  /api/subscriptions/{id}      — update a subscription
- DELETE /api/subscriptions/{id}      — delete a subscription

Each subscription stores a list of plain-English keywords.  On create /
update the keywords are concatenated and embedded via
``app.services.embeddings.embed()`` — the resulting vector is stored on
the row and used by the M5 matching engine for cosine similarity against
newly scored ChangeEvent embeddings.

Embedding failures are non-fatal: the subscription is saved without an
embedding (``embedding=NULL``) and the user is warned in the response.
The subscription will simply be skipped at match time until the embedding
is populated (e.g. by a backfill or next update).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.logging_setup import get_logger
from app.models import UserSubscription

log = get_logger(__name__)
router = APIRouter(prefix="/api/subscriptions", tags=["M5 Subscriptions"])


# ── Request / Response schemas ───────────────────────────────────────────────

class SubscriptionCreate(BaseModel):
    user_email: str = Field(..., min_length=3, max_length=255,
                            examples=["sarah@acme.com"])
    label: str = Field(default="Default Subscription", max_length=255,
                       examples=["My Battery Watch"])
    keywords: list[str] = Field(
        ..., min_length=1,
        examples=[["lithium battery", "import tariff", "CBAM"]],
        description="Plain-English keywords. All are concatenated and embedded together.",
    )
    min_significance: float = Field(default=0.6, ge=0.0, le=1.0)
    similarity_threshold: float = Field(
        default=0.72, ge=0.0, le=1.0,
        description="Cosine similarity cutoff. Lower = more alerts, higher = fewer.",
    )


class SubscriptionUpdate(BaseModel):
    label: Optional[str] = None
    keywords: Optional[list[str]] = None
    min_significance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None


class SubscriptionRead(BaseModel):
    id: UUID
    user_email: str
    label: str
    keywords: list[str]
    similarity_threshold: float
    min_significance: float
    is_active: bool
    embedding_ready: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, sub: UserSubscription) -> "SubscriptionRead":
        return cls(
            id=sub.id,
            user_email=sub.user_email,
            label=sub.label,
            keywords=sub.keywords or [],
            similarity_threshold=sub.similarity_threshold,
            min_significance=sub.min_significance,
            is_active=sub.is_active,
            embedding_ready=sub.embedding is not None,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        )


# ── Embedding helper ─────────────────────────────────────────────────────────

def _try_embed(keywords: list[str]) -> Optional[list[float]]:
    """Embed keywords; return None (+ log warning) on any failure."""
    from app.services.embeddings import build_subscription_text, embed
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        log.warning("subscription_embed_skipped", reason="no_api_key")
        return None
    if not keywords:
        return None
    try:
        return embed(build_subscription_text(keywords))
    except Exception as exc:
        log.warning("subscription_embed_failed",
                    error=str(exc), error_type=type(exc).__name__)
        return None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=SubscriptionRead, status_code=201)
def create_subscription(
    body: SubscriptionCreate,
    session: Session = Depends(get_session),
):
    keywords = [k.strip() for k in body.keywords if k.strip()]
    sub = UserSubscription(
        user_email=body.user_email,
        label=body.label,
        keywords=keywords,
        min_significance=body.min_significance,
        similarity_threshold=body.similarity_threshold,
        embedding=_try_embed(keywords),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    log.info("subscription_created", sub_id=str(sub.id),
             email=sub.user_email, keyword_count=len(keywords),
             embedding_ready=sub.embedding is not None)
    return SubscriptionRead.from_orm(sub)


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(
    email: str,
    session: Session = Depends(get_session),
):
    stmt = (
        select(UserSubscription)
        .where(UserSubscription.user_email == email)
        .order_by(UserSubscription.created_at.desc())
    )
    return [SubscriptionRead.from_orm(s) for s in session.exec(stmt).all()]


@router.patch("/{subscription_id}", response_model=SubscriptionRead)
def update_subscription(
    subscription_id: UUID,
    body: SubscriptionUpdate,
    session: Session = Depends(get_session),
):
    sub = session.get(UserSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    update_data = body.model_dump(exclude_unset=True)

    if "keywords" in update_data:
        keywords = [k.strip() for k in update_data["keywords"] if k.strip()]
        update_data["keywords"] = keywords
        update_data["embedding"] = _try_embed(keywords)

    for key, value in update_data.items():
        setattr(sub, key, value)
    sub.updated_at = datetime.now(timezone.utc)

    session.add(sub)
    session.commit()
    session.refresh(sub)
    return SubscriptionRead.from_orm(sub)


@router.delete("/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: UUID,
    session: Session = Depends(get_session),
):
    sub = session.get(UserSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    from app.models import Alert
    for alert in session.exec(
        select(Alert).where(Alert.subscription_id == subscription_id)
    ).all():
        session.delete(alert)

    session.delete(sub)
    session.commit()
