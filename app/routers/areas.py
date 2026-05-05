"""
`/api/v2/areas` — the user's "areas of interest" profile, as the regwatch
admin frontend models it.

The frontend exposes a single profile per user with three lists:

  - hsCodes   : selected HS codes (e.g. ["854140", "850440"])
  - countries : ISO-2 country codes (e.g. ["US", "CN", "EU"])
  - keywords  : free-text concepts (e.g. ["semiconductor", "export control"])

Internally this maps onto the existing UserSubscription table — we treat
the user's first (or newest) subscription as their "primary" profile and
upsert it on PUT. Multiple subscriptions per user remain supported through
/api/subscriptions but are not surfaced here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.logging_setup import get_logger
from app.models import UserSubscription


log = get_logger(__name__)
router = APIRouter(prefix="/api/v2/areas", tags=["Frontend Areas (v2)"])


# ── Schemas ───────────────────────────────────────────────────────────

class AreasProfile(BaseModel):
    """The frontend's view of a user's areas-of-interest profile."""
    email: str = Field(..., min_length=3, max_length=255)
    hsCodes: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────

def _primary_subscription(
    session: Session, email: str
) -> Optional[UserSubscription]:
    """Return the user's primary (newest) subscription, or None."""
    stmt = (
        select(UserSubscription)
        .where(UserSubscription.user_email == email)
        .order_by(UserSubscription.created_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def _try_embed(keywords: list[str]) -> Optional[list[float]]:
    """Compute the keyword embedding; return None (+ log) on any failure."""
    from app.config import get_settings
    from app.services.embeddings import build_subscription_text, embed

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        log.warning("areas_embed_skipped", reason="no_api_key")
        return None
    if not keywords:
        return None
    try:
        return embed(build_subscription_text(keywords))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "areas_embed_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


def _to_profile(sub: UserSubscription) -> AreasProfile:
    return AreasProfile(
        email=sub.user_email,
        hsCodes=sub.hs_codes or [],
        countries=sub.countries or [],
        keywords=sub.keywords or [],
    )


def _empty_profile(email: str) -> AreasProfile:
    return AreasProfile(email=email, hsCodes=[], countries=[], keywords=[])


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=AreasProfile)
def get_areas(
    email: str = Query(..., min_length=3, description="User email"),
    session: Session = Depends(get_session),
):
    """Return the user's saved profile, or an empty one if they have none."""
    sub = _primary_subscription(session, email)
    if sub is None:
        return _empty_profile(email)
    return _to_profile(sub)


@router.put("", response_model=AreasProfile)
def upsert_areas(
    body: AreasProfile,
    session: Session = Depends(get_session),
):
    """
    Save the user's areas-of-interest profile.

    - Creates a new subscription if the user has none.
    - Updates the existing primary one otherwise.
    - Re-computes the keyword embedding so the matching engine can use it.
    """
    # Normalize: strip whitespace, dedupe, drop empties
    def _clean(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for v in values:
            s = (v or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    hs_codes = _clean(body.hsCodes)
    countries = [c.upper() for c in _clean(body.countries)]
    keywords = _clean(body.keywords)

    sub = _primary_subscription(session, body.email)
    now = datetime.now(timezone.utc)

    if sub is None:
        sub = UserSubscription(
            user_email=body.email,
            label="Areas of Interest",
            hs_codes=hs_codes,
            countries=countries,
            keywords=keywords,
            embedding=_try_embed(keywords),
        )
    else:
        sub.hs_codes = hs_codes
        sub.countries = countries
        # Only re-embed if keywords actually changed (saves an OpenAI call)
        if keywords != (sub.keywords or []):
            sub.keywords = keywords
            sub.embedding = _try_embed(keywords)
        sub.updated_at = now

    session.add(sub)
    session.commit()
    session.refresh(sub)

    log.info(
        "areas_saved",
        sub_id=str(sub.id),
        email=sub.user_email,
        hs_count=len(hs_codes),
        country_count=len(countries),
        keyword_count=len(keywords),
        embedding_ready=sub.embedding is not None,
    )
    return _to_profile(sub)
