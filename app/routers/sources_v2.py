"""
`/api/v2/sources` — frontend-shaped view over the `domains` table.

The regwatch admin's SourcesView (frontend/src/app/components/sources-view.tsx)
expects rows like:

    {
      id, name, url, type: "web"|"rss"|"email"|"api"|"database",
      status: "active"|"inactive",
      lastActivity, activityCount, activityMetric,
      addedDate, frequency, userSubscribed, countryCode?
    }

Internally we have `Domain` (id, domain, seed_urls, status, ...) and
`FetchRun` (per-crawl metrics). This router joins them and derives the
fields the frontend needs. Stubbed fields (`userSubscribed`, `frequency`)
are returned as defaults until we model them properly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.logging_setup import get_logger
from app.models import Domain, FetchRun
from app.services.alert_adapter import _AUTHORITY_BY_HOST  # reuse mapping
from app.services.frequency import (
    label_for_seconds,
    seconds_for_label,
    valid_labels,
)


log = get_logger(__name__)
router = APIRouter(prefix="/api/v2/sources", tags=["Frontend Sources (v2)"])


# ── Schemas ───────────────────────────────────────────────────────────

SourceType = str  # "web" | "rss" | "email" | "api" | "database"
SourceStatus = str  # "active" | "inactive"


class SourceItem(BaseModel):
    id: str
    name: str
    url: str
    type: SourceType
    status: SourceStatus
    lastActivity: Optional[str] = None
    activityCount: int = 0
    activityMetric: str = "pages"
    addedDate: str
    frequency: str = "Daily"
    # Per-source crawl page cap. None means "use the platform default";
    # the frontend should display the resolved effective value rather
    # than null so users see what will actually happen.
    maxPages: int = 50
    userSubscribed: bool = True
    countryCode: Optional[str] = None


_FREQUENCY_PATTERN = "^(Hourly|Daily|Weekly|Monthly)$"


class SourcePatch(BaseModel):
    """PATCH body — every field is optional, set only what changes."""
    status: Optional[SourceStatus] = Field(
        default=None, pattern="^(active|inactive)$",
    )
    name: Optional[str] = Field(default=None, max_length=255)
    frequency: Optional[str] = Field(default=None, pattern=_FREQUENCY_PATTERN)
    maxPages: Optional[int] = Field(default=None, ge=1, le=10000)
    userSubscribed: Optional[bool] = None


class SourceCreate(BaseModel):
    """Body for `POST /api/v2/sources` — the dialog's form."""
    name: Optional[str] = Field(default=None, max_length=255)
    url: str = Field(..., min_length=4, max_length=512)
    frequency: Optional[str] = Field(default=None, pattern=_FREQUENCY_PATTERN)
    maxPages: Optional[int] = Field(default=None, ge=1, le=10000)


class CrawlNowResponse(BaseModel):
    """Response of `POST /api/v2/sources/:id/crawl-now`."""
    ok: bool
    task_id: Optional[str] = None
    domain: str
    seed_urls: list[str]


# ── Mapping helpers ──────────────────────────────────────────────────

_TYPE_TO_METRIC = {
    "web": "pages",
    "rss": "items",
    "email": "messages",
    "api": "records",
    "database": "entries",
}


def _infer_type(domain: Domain) -> SourceType:
    """Guess the connector type from the seed URL."""
    seed = (domain.seed_urls or [""])[0] if domain.seed_urls else ""
    seed_l = seed.lower()
    if "@" in seed and "://" not in seed:
        return "email"
    if seed_l.endswith((".rss", ".xml")) or "/rss" in seed_l or "/feed" in seed_l:
        return "rss"
    if "/api/" in seed_l or seed_l.startswith("api."):
        return "api"
    return "web"


def _infer_country(host: str) -> Optional[str]:
    """Derive an ISO-2 country code from a domain hostname."""
    if not host:
        return None
    host = host.lower()
    if host.endswith(".eu") or "europa.eu" in host:
        return "EU"
    if host.endswith(".uk") or host.endswith(".gov.uk"):
        return "GB"
    if host.endswith(".cn") or host.endswith(".gov.cn"):
        return "CN"
    if host.endswith(".jp") or host.endswith(".gov.jp") or host.endswith(".go.jp"):
        return "JP"
    if host.endswith(".in") or host.endswith(".gov.in"):
        return "IN"
    if host.endswith(".sg") or host.endswith(".gov.sg"):
        return "SG"
    if host.endswith(".br") or host.endswith(".gov.br"):
        return "BR"
    if host.endswith(".au") or host.endswith(".gov.au"):
        return "AU"
    if host.endswith(".ca") or host.endswith(".gc.ca"):
        return "CA"
    if host.endswith(".gov") or "doc.gov" in host or "ustr.gov" in host:
        return "US"
    return None


def _name_for_domain(domain: Domain) -> str:
    """Human-readable name for the source.

    User-supplied `Domain.label` always wins. Otherwise we fall back to
    the authority lookup, then a prettified hostname.
    """
    if domain.label and domain.label.strip():
        return domain.label.strip()
    seed = (domain.seed_urls or [""])[0] if domain.seed_urls else ""
    try:
        host = urlparse(seed).hostname or domain.domain
    except Exception:
        host = domain.domain
    if host and host.lower() in _AUTHORITY_BY_HOST:
        return _AUTHORITY_BY_HOST[host.lower()]
    if host and host.lower().startswith("www."):
        stripped = host.lower()[4:]
        if stripped in _AUTHORITY_BY_HOST:
            return _AUTHORITY_BY_HOST[stripped]
    # Fallback: pretty-print the domain string itself.
    return (domain.domain or host or "").replace("-", " ").title()


def _last_fetch_run(session: Session, domain_id: UUID) -> Optional[FetchRun]:
    """Most recent FetchRun for this domain."""
    stmt = (
        select(FetchRun)
        .where(FetchRun.domain_id == domain_id)
        .order_by(FetchRun.started_at.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def _build_source(session: Session, d: Domain) -> SourceItem:
    from app.config import get_settings

    seed = (d.seed_urls or [""])[0] if d.seed_urls else ""
    if not seed:
        seed = f"https://{d.domain}"
    try:
        host = urlparse(seed).hostname or d.domain
    except Exception:
        host = d.domain
    last = _last_fetch_run(session, d.id)
    src_type = _infer_type(d)

    # Resolve effective max_pages: per-source override OR platform default.
    # Surface the resolved value rather than NULL so the frontend always
    # shows what will actually happen on the next crawl.
    s = get_settings()
    effective_max_pages = d.max_pages or s.CRAWL_DEFAULT_MAX_PAGES

    return SourceItem(
        id=str(d.id),
        name=_name_for_domain(d),
        url=seed,
        type=src_type,
        # Domain.status: active/paused/archived → frontend wants active/inactive
        status="active" if d.status == "active" else "inactive",
        lastActivity=last.finished_at.isoformat()
        if last and last.finished_at
        else (last.started_at.isoformat() if last else None),
        activityCount=last.fetched_count if last else 0,
        activityMetric=_TYPE_TO_METRIC.get(src_type, "pages"),
        addedDate=d.created_at.date().isoformat(),
        frequency=label_for_seconds(d.crawl_interval_seconds),
        maxPages=effective_max_pages,
        userSubscribed=True,  # stub — no user↔source link yet
        countryCode=_infer_country(host or ""),
    )


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("", response_model=list[SourceItem])
def list_sources(session: Session = Depends(get_session)):
    """List every registered source, shaped for the frontend."""
    stmt = select(Domain).order_by(Domain.created_at.desc())
    return [_build_source(session, d) for d in session.exec(stmt).all()]


@router.post("", response_model=SourceItem, status_code=201)
def create_source(
    body: SourceCreate,
    session: Session = Depends(get_session),
):
    """
    Register a new source. The crawler will pick it up on the next
    scheduled beat run (or via `/api/admin/trigger-crawl`).

    The body supplies a URL or email address. We extract a domain key,
    check it doesn't already exist, then insert a Domain row using the
    URL as the seed.
    """
    raw_url = body.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="url is required")

    # Email-style addresses (alerts@example.gov) → use the right-hand side
    # as the domain key, store the full address as seed for the Email
    # connector.
    if "@" in raw_url and "://" not in raw_url:
        try:
            domain_key = raw_url.split("@", 1)[1].lower().strip()
        except IndexError:
            raise HTTPException(status_code=400, detail="invalid email address")
        seed = raw_url
    else:
        # Auto-prepend https:// if missing so urlparse extracts a hostname.
        if "://" not in raw_url:
            raw_url = "https://" + raw_url
        try:
            host = urlparse(raw_url).hostname
        except Exception:
            host = None
        if not host:
            raise HTTPException(status_code=400, detail="could not parse a host from the URL")
        domain_key = host.lower()
        seed = raw_url

    if not domain_key:
        raise HTTPException(status_code=400, detail="could not derive a domain key")

    # Reject duplicates — same UNIQUE constraint as POST /domains.
    existing = session.exec(
        select(Domain).where(Domain.domain == domain_key)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Source for domain '{domain_key}' already exists",
        )

    # URL reachability check. Saves users from typing "https://typo.gov.fake"
    # and waiting forever for nothing to happen. Email-style addresses skip
    # this check (no HTTP endpoint to probe).
    if "://" in seed:
        import httpx
        try:
            with httpx.Client(
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "regwatch-add-source-check/1.0"},
            ) as client:
                # HEAD first; some sites refuse HEAD, fall back to a small GET.
                r = client.head(seed)
                if r.status_code in (405, 501) or r.status_code >= 400:
                    r = client.get(seed)
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"URL returned HTTP {r.status_code}. "
                        "Check that the address is correct and publicly reachable."
                    ),
                )
        except HTTPException:
            raise
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"URL is not reachable: {exc.__class__.__name__}: {exc}",
            )

    label = (body.name or "").strip() or None
    interval = seconds_for_label(body.frequency)
    d = Domain(
        domain=domain_key,
        seed_urls=[seed],
        label=label,
        crawl_interval_seconds=interval,
        max_pages=body.maxPages,
    )
    session.add(d)
    session.commit()
    session.refresh(d)

    log.info(
        "source_created",
        source_id=str(d.id),
        domain=d.domain,
        seed=seed,
        label=label,
        interval_seconds=interval,
    )
    return _build_source(session, d)


@router.patch("/{source_id}", response_model=SourceItem)
def patch_source(
    source_id: UUID,
    body: SourcePatch,
    session: Session = Depends(get_session),
):
    """
    Update a source. Persisted fields:
      - status     (active ⇄ inactive, mapped to Domain.status active/paused)
      - name       (stored as Domain.label; empty string clears it)
      - frequency  ("Hourly|Daily|Weekly|Monthly", stored as seconds)

    Stubbed (accepted, returned successfully, NOT persisted):
      - userSubscribed  (no user↔source link yet)
    """
    d = session.get(Domain, source_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Source not found")

    dirty = False
    if body.status is not None:
        # Frontend "active" → DB "active"; "inactive" → DB "paused" (we keep
        # "archived" as a separate hard-disabled state set by other tooling).
        d.status = "active" if body.status == "active" else "paused"
        dirty = True
    if body.name is not None:
        d.label = body.name.strip() or None
        dirty = True
    if body.frequency is not None:
        d.crawl_interval_seconds = seconds_for_label(body.frequency)
        dirty = True
    if body.maxPages is not None:
        d.max_pages = body.maxPages
        dirty = True

    if dirty:
        session.add(d)
        session.commit()
        session.refresh(d)

    # `userSubscribed` is intentionally swallowed for now.
    return _build_source(session, d)


@router.post("/{source_id}/crawl-now", response_model=CrawlNowResponse)
def crawl_now(
    source_id: UUID,
    session: Session = Depends(get_session),
):
    """
    Trigger an immediate crawl of this source, bypassing the schedule.

    Used by the "Crawl Now" button on each row in the sources list. The
    actual crawl runs asynchronously on the Celery worker — we return as
    soon as the task is enqueued.
    """
    d = session.get(Domain, source_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if d.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Source is paused — set it back to active first",
        )

    seed_urls = list(d.seed_urls or [])
    if not seed_urls:
        # Fall back to https://<domain> if no explicit seed was stored.
        seed_urls = [f"https://{d.domain}"]

    # Import lazily so the router can be loaded without celery_app's
    # heavy side-effects in tests.
    from app.celery_app import web_crawl_task
    from app.config import get_settings

    s = get_settings()
    effective_max_pages = d.max_pages or s.CRAWL_DEFAULT_MAX_PAGES

    try:
        async_result = web_crawl_task.delay(
            seed_urls=seed_urls,
            allowed_domain=d.domain,
            max_pages=effective_max_pages,
            rate_limit_rps=max(1.0, d.rate_limit_rps),
        )
    except Exception as exc:  # broker unreachable
        log.warning(
            "crawl_now_enqueue_failed",
            source_id=str(source_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not enqueue crawl: {exc.__class__.__name__}: {exc}",
        )

    log.info(
        "crawl_now_enqueued",
        source_id=str(source_id),
        domain=d.domain,
        task_id=async_result.id,
    )
    return CrawlNowResponse(
        ok=True,
        task_id=async_result.id,
        domain=d.domain,
        seed_urls=seed_urls,
    )
