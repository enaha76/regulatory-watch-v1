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

import csv
import io
import re
from datetime import datetime, timezone
from typing import Optional as _Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select


# Federal Register document numbers look like "2026-09007". The same
# notice publishes under multiple URL shapes (mods.xml, full_text/xml,
# documents/.../slug) so we use this number as a cross-source primary
# key to dedupe the inbox. Pattern is intentionally permissive about
# the surrounding boundary so the regex catches the id whether it sits
# at a path segment or before a file extension.
_FR_DOCNUM_RE = re.compile(r"/(\d{4}-\d{4,7})(?:[./]|$)")


def _fr_doc_number(url: _Optional[str]) -> _Optional[str]:
    """Extract the canonical Federal Register document number from any
    `federalregister.gov` or `govinfo.gov` URL — the API's primary key
    for the underlying notice. Returns None for URLs that don't look
    like FR documents (CBP slip-opinions, mock-website, DGFT, etc.)."""
    if not url:
        return None
    m = _FR_DOCNUM_RE.search(url)
    if not m:
        return None
    return m.group(1)

from app.database import get_session
from app.models import Alert, ChangeEvent, Obligation, UserSubscription
from app.services.alert_adapter import (
    build_frontend_alert,
    status_fe_to_be,
)
from app.services.auth import CurrentUser, get_current_user


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
        description="(Admin) Override the auth-derived email to inspect another user's alerts.",
    ),
    status: Optional[str] = Query(
        default=None,
        pattern="^(new|read|archived)$",
        description="Frontend status filter",
    ),
    q: Optional[str] = Query(
        default=None,
        max_length=200,
        description="Free-text search across headline, summary, authority, "
                    "and source URL. Server-side ILIKE; case-insensitive.",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    """
    List alerts shaped for the regwatch admin frontend.

    Most-recent first. Returns the calling user's alerts only, unless
    they're an ``admin`` and pass ``?email=other@user.com`` to inspect
    someone else's view, OR ``?email=*`` to see every alert in the
    system (legacy admin behaviour).

    Dedup: a single regulatory ChangeEvent typically matches multiple
    user subscriptions, generating one alert row per subscription. The
    view collapses these into one row per ChangeEvent so the inbox
    shows real changes, not subscription-fanout duplicates. The
    most-recent alert per event wins; pin/feedback state of the other
    matching alerts is preserved on those rows in the DB.
    """
    # Resolve which subscriptions the caller is allowed to read.
    # - `?email=*`        — admin only, every alert in the system
    # - `?email=foo@bar`  — admin only, that specific user's alerts
    # - omitted           — the caller's own alerts (default)
    stmt = select(Alert)
    target_email: Optional[str]
    if email == "*":
        if not user.has_role("admin"):
            raise HTTPException(
                status_code=403,
                detail="Admin role required to list alerts across all users",
            )
        target_email = None  # no filter — every alert
    elif email is not None and email != user.email:
        if not user.has_role("admin"):
            raise HTTPException(
                status_code=403,
                detail="Admin role required to inspect another user's alerts",
            )
        target_email = email
    else:
        target_email = user.email

    if target_email is not None:
        sub_ids = list(
            session.exec(
                select(UserSubscription.id).where(
                    UserSubscription.user_email == target_email
                )
            ).all()
        )
        if not sub_ids:
            return []
        stmt = stmt.where(Alert.subscription_id.in_(sub_ids))

    if status:
        stmt = stmt.where(Alert.status == status_fe_to_be(status))

    # Server-side search. Joins change_events (where the searchable
    # text actually lives — headline, summary, authority via URL)
    # and applies an ILIKE on each field. The previous client-side
    # filter capped at 200 rows, so the regulatory search page
    # silently missed anything past that.
    if q:
        from sqlalchemy import or_
        like = f"%{q.strip()}%"
        stmt = stmt.join(ChangeEvent, ChangeEvent.id == Alert.change_event_id).where(
            or_(
                ChangeEvent.headline.ilike(like),  # type: ignore[union-attr]
                ChangeEvent.summary.ilike(like),  # type: ignore[union-attr]
                ChangeEvent.source_url.ilike(like),  # type: ignore[union-attr]
            )
        )

    # Over-fetch so dedup doesn't starve us of rows. Cap the multiplier
    # so a pathological 100x-fanout doesn't blow up the query.
    overfetch = min(limit * 3, 1500)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(overfetch)

    out: list[dict] = []
    seen_event_ids: set = set()
    # Cross-source dedup. A single FR notice publishes under multiple
    # URL shapes (mods.xml, full_text/xml, documents/...), each producing
    # its own ChangeEvent. Without this, the inbox shows the same
    # regulation 2-3 times. We collapse on FR document number so the
    # user sees the notice once. First match wins (event rows arrive
    # newest-first, so the freshest crawl's row is what surfaces).
    seen_fr_doc_numbers: set[str] = set()
    for alert in session.exec(stmt).all():
        if alert.change_event_id in seen_event_ids:
            continue
        seen_event_ids.add(alert.change_event_id)

        event = session.get(ChangeEvent, alert.change_event_id)
        if event is None:
            # Orphaned row — skip silently rather than crash the whole list
            continue
        fr_doc = _fr_doc_number(event.source_url)
        if fr_doc is not None:
            if fr_doc in seen_fr_doc_numbers:
                continue
            seen_fr_doc_numbers.add(fr_doc)
        out.append(build_frontend_alert(session, alert, event))
        if len(out) >= limit:
            break
    return out


@router.get("/export.csv")
def export_alerts_csv(
    email: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(new|read|archived)$"),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Export the calling user's alerts as a CSV file. Same auth + filter
    semantics as `GET /api/v2/alerts` (the list endpoint), but without
    the inbox dedup — auditors generally want every row, including
    duplicates from multiple subscriptions, so they can reconcile against
    their own systems.

    Columns are stable and ordered for downstream Excel/Sheets imports.
    Includes a deadline summary derived from the obligations rollup so
    a reviewer can sort by "next deadline" in their spreadsheet.
    """
    target_email: Optional[str]
    if email == "*":
        if not user.has_role("admin"):
            raise HTTPException(403, detail="Admin role required for ?email=*")
        target_email = None
    elif email is not None and email != user.email:
        if not user.has_role("admin"):
            raise HTTPException(
                403, detail="Admin role required to export another user's alerts",
            )
        target_email = email
    else:
        target_email = user.email

    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(5000)
    if target_email is not None:
        sub_ids = list(
            session.exec(
                select(UserSubscription.id).where(
                    UserSubscription.user_email == target_email
                )
            ).all()
        )
        if not sub_ids:
            sub_ids = []
        stmt = stmt.where(Alert.subscription_id.in_(sub_ids))
    if status:
        stmt = stmt.where(Alert.status == status_fe_to_be(status))

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow([
        "alert_id", "created_at", "status", "user_feedback", "pinned",
        "title", "country", "authority", "regulation_type",
        "publication_date", "relevance_score", "trade_lane",
        "affected_products", "summary", "next_deadline",
        "obligation_count", "source_url",
    ])

    for alert in session.exec(stmt).all():
        event = session.get(ChangeEvent, alert.change_event_id)
        if event is None:
            continue
        row = build_frontend_alert(
            session, alert, event, include_summary_bullets=True,
        )
        # Earliest non-null deadline across the obligations rollup.
        next_deadline = ""
        obs = session.exec(
            select(Obligation)
            .where(Obligation.change_event_id == event.id)
            .where(Obligation.deadline_date.is_not(None))  # type: ignore[union-attr]
            .order_by(Obligation.deadline_date.asc())  # type: ignore[union-attr]
            .limit(1)
        ).first()
        if obs and obs.deadline_date:
            next_deadline = obs.deadline_date.isoformat()
        ob_count = session.exec(
            select(Obligation.id).where(Obligation.change_event_id == event.id)
        ).all()
        summary_text = " ".join(row.get("summary") or []) or (event.summary or "")
        w.writerow([
            row.get("id", ""),
            alert.created_at.isoformat() if alert.created_at else "",
            row.get("status", ""),
            row.get("userFeedback") or "",
            "yes" if row.get("pinned") else "no",
            row.get("title", ""),
            row.get("country", ""),
            row.get("authority", ""),
            row.get("regulationType", ""),
            row.get("publicationDate", ""),
            row.get("relevanceScore", ""),
            row.get("tradeLane", ""),
            "; ".join(row.get("affectedProducts") or []),
            summary_text,
            next_deadline,
            len(ob_count),
            row.get("sourceUrl", ""),
        ])

    buf.seek(0)
    filename = f"regwatch-alerts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/{alert_id}", response_model=dict)
def get_alert_v2(
    alert_id: UUID,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — auth gate only
):
    """Single alert detail — adds a `summary` bullet array."""
    alert, event = _resolve_alert(session, alert_id)
    return build_frontend_alert(session, alert, event, include_summary_bullets=True)


@router.patch("/{alert_id}", response_model=dict)
def update_alert_v2(
    alert_id: UUID,
    body: AlertPatch,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — auth gate only
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
