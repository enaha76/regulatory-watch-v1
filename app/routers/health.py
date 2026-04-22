"""
Health-check endpoints.
GET /health       — API liveness
GET /health/db    — PostgreSQL connectivity
GET /health/redis — Redis connectivity
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, text
import redis as redis_lib

from app.database import get_session
from app.config import get_settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health():
    """API liveness check."""
    return {"status": "healthy"}


@router.get("/db")
def health_db(session: Session = Depends(get_session)):
    """Check PostgreSQL connectivity."""
    try:
        session.exec(text("SELECT 1"))
        return {"status": "healthy", "service": "postgresql"}
    except Exception as e:
        return {"status": "unhealthy", "service": "postgresql", "error": str(e)}


@router.get("/redis")
async def health_redis():
    """Check Redis connectivity."""
    settings = get_settings()
    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.ping()
        return {"status": "healthy", "service": "redis"}
    except Exception as e:
        return {"status": "unhealthy", "service": "redis", "error": str(e)}
