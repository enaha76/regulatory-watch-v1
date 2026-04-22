"""
CRUD endpoints for Domain management.
POST   /domains       — register a new domain
GET    /domains       — list domains (paginated)
GET    /domains/{id}  — get a single domain
PATCH  /domains/{id}  — partial update
DELETE /domains/{id}  — remove a domain
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from uuid import UUID
from datetime import datetime, timezone

from app.database import get_session
from app.models import Domain
from app.schemas import DomainCreate, DomainUpdate, DomainRead, DomainList

router = APIRouter(prefix="/domains", tags=["Domains"])


@router.post("", status_code=201, response_model=DomainRead)
def create_domain(
    payload: DomainCreate,
    session: Session = Depends(get_session),
):
    """Register a new regulatory domain to monitor."""
    # Check for duplicate
    existing = session.exec(
        select(Domain).where(Domain.domain == payload.domain)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Domain '{payload.domain}' already exists")

    domain = Domain(
        domain=payload.domain,
        seed_urls=payload.seed_urls,
        rate_limit_rps=payload.rate_limit_rps,
    )
    session.add(domain)
    session.commit()
    session.refresh(domain)
    return domain


@router.get("", response_model=DomainList)
def list_domains(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(active|paused|archived)$"),
    session: Session = Depends(get_session),
):
    """List all domains with pagination and optional status filter."""
    query = select(Domain)
    count_query = select(func.count()).select_from(Domain)

    if status:
        query = query.where(Domain.status == status)
        count_query = count_query.where(Domain.status == status)

    total = session.exec(count_query).one()
    domains = session.exec(query.offset(skip).limit(limit)).all()

    return DomainList(items=domains, total=total, skip=skip, limit=limit)


@router.get("/{domain_id}", response_model=DomainRead)
def get_domain(
    domain_id: UUID,
    session: Session = Depends(get_session),
):
    """Get a single domain by ID."""
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.patch("/{domain_id}", response_model=DomainRead)
def update_domain(
    domain_id: UUID,
    payload: DomainUpdate,
    session: Session = Depends(get_session),
):
    """Partially update a domain."""
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(domain, key, value)

    domain.updated_at = datetime.now(timezone.utc)
    session.add(domain)
    session.commit()
    session.refresh(domain)
    return domain


@router.delete("/{domain_id}", status_code=204)
def delete_domain(
    domain_id: UUID,
    session: Session = Depends(get_session),
):
    """Delete a domain."""
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    session.delete(domain)
    session.commit()
