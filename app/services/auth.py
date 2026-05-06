"""
JWT validation against the Keycloak realm.

Exposes a single ``get_current_user`` FastAPI dependency:

    from app.services.auth import get_current_user, CurrentUser

    @router.get("/me")
    def me(user: CurrentUser = Depends(get_current_user)):
        return {"email": user.email}

Behaviour:
  - Authorization: Bearer <jwt>  → validate signature, audience, expiry,
    extract email + sub + roles.
  - Missing or empty header in dev mode (``APP_ENV == "dev"`` and
    ``AUTH_ALLOW_DEV_FALLBACK``) → return a synthetic dev user. Lets
    backend devs hit the API without booting the full OIDC flow.
  - Anything else → 401 Unauthorized.

JWKS keys are cached per process for 5 minutes — Keycloak rotates
infrequently and a network hop on every request would be wasteful.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Optional

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from app.config import get_settings


@dataclass
class CurrentUser:
    """Caller identity extracted from the validated JWT."""

    sub: str
    email: str
    name: Optional[str] = None
    roles: list[str] = field(default_factory=list)
    is_dev_fallback: bool = False

    def has_role(self, role: str) -> bool:
        return role in self.roles


# ── JWKS cache ────────────────────────────────────────────────────────

_JWKS_CACHE: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 300  # 5 minutes


def _fetch_jwks(issuer: str, jwks_url_override: Optional[str] = None) -> dict[str, Any]:
    """
    Fetch the public keys, with a 5-minute cache.

    `jwks_url_override` lets the backend reach Keycloak at a different
    network address than the one in the token's ``iss`` claim — common
    in Docker setups where the frontend uses localhost:8085 but the
    api container reaches Keycloak via host.docker.internal:8085.
    """
    now = time.time()
    cached = _JWKS_CACHE.get("keys")
    fetched = float(_JWKS_CACHE.get("fetched_at") or 0)
    if cached and (now - fetched) < _JWKS_TTL_SECONDS:
        return cached
    url = jwks_url_override or f"{issuer.rstrip('/')}/protocol/openid-connect/certs"
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url)
            res.raise_for_status()
            jwks = res.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not fetch OIDC keys from {url}: {exc}",
        )
    _JWKS_CACHE["keys"] = jwks
    _JWKS_CACHE["fetched_at"] = now
    return jwks


def _decode_token(token: str, jwks: dict[str, Any], audience: str, issuer: str) -> dict[str, Any]:
    """
    Validate signature, expiry, and basic claims. Raises HTTPException
    on any failure with a readable detail string.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    kid = header.get("kid")
    matching_key = next(
        (k for k in jwks.get("keys", []) if k.get("kid") == kid),
        None,
    )
    if matching_key is None:
        # Force a refresh in case the realm rotated keys.
        _JWKS_CACHE["fetched_at"] = 0.0
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unknown signing key (kid={kid})",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Keycloak's tokens have audience set to the resource server's
        # client_id (or "account") — we accept either.
        return jwt.decode(
            token,
            matching_key,
            algorithms=[header.get("alg", "RS256")],
            audience=audience,
            issuer=issuer,
            options={"verify_at_hash": False},
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _user_from_claims(claims: dict[str, Any]) -> CurrentUser:
    """Map a verified token's claim set into our CurrentUser dataclass."""
    realm_roles = (
        claims.get("realm_access", {}).get("roles", []) if claims else []
    )
    return CurrentUser(
        sub=str(claims.get("sub") or ""),
        email=str(claims.get("email") or ""),
        name=claims.get("name") or claims.get("preferred_username"),
        roles=list(realm_roles),
        is_dev_fallback=False,
    )


# ── FastAPI dependency ────────────────────────────────────────────────


def get_current_user(
    authorization: Annotated[Optional[str], Header()] = None,
) -> CurrentUser:
    """
    Validate the Authorization header and return the calling user.

    See module docstring for the dev-fallback behaviour.
    """
    settings = get_settings()

    if not authorization:
        if settings.APP_ENV == "dev" and settings.AUTH_ALLOW_DEV_FALLBACK:
            return CurrentUser(
                sub="dev-user",
                email=settings.AUTH_DEV_FALLBACK_EMAIL,
                name="Dev User",
                roles=["user", "admin"],
                is_dev_fallback=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    jwks = _fetch_jwks(
        settings.KEYCLOAK_ISSUER,
        jwks_url_override=settings.KEYCLOAK_JWKS_URL or None,
    )
    claims = _decode_token(
        token, jwks, settings.KEYCLOAK_AUDIENCE, settings.KEYCLOAK_ISSUER
    )
    return _user_from_claims(claims)


def require_role(role: str):
    """Build a dependency that 403s unless the user has the given role."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user

    return _dep
