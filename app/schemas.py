"""
Pydantic schemas for API request/response bodies.
Separate from SQLModel table models to control what the API exposes.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime


# ── Domain Schemas ───────────────────────────────────────────────────────────

class DomainCreate(BaseModel):
    """POST /domains request body."""
    domain: str = Field(..., min_length=3, max_length=255, examples=["cbp.gov"])
    seed_urls: list[str] = Field(default=[], examples=[["https://www.cbp.gov/trade/rulings"]])
    rate_limit_rps: float = Field(default=1.0, ge=0.1, le=10.0)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, v: str) -> str:
        """Strip protocol and trailing slashes."""
        v = v.strip().lower()
        for prefix in ("https://", "http://", "www."):
            if v.startswith(prefix):
                v = v[len(prefix):]
        return v.rstrip("/")


class DomainUpdate(BaseModel):
    """PATCH /domains/{id} request body. All fields optional."""
    seed_urls: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|paused|archived)$")
    rate_limit_rps: Optional[float] = Field(default=None, ge=0.1, le=10.0)


class DomainRead(BaseModel):
    """Response schema for Domain."""
    id: UUID
    domain: str
    seed_urls: list[str]
    status: str
    rate_limit_rps: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DomainList(BaseModel):
    """Paginated list response."""
    items: list[DomainRead]
    total: int
    skip: int
    limit: int
