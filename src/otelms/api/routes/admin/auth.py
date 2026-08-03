"""Admin authentication: login, JWT session tokens, and auth dependencies."""

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.config.settings import settings
from otelms.domain.entities import ApiKey
from otelms.domain.repositories.database import get_db_session
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


class LoginRequest(BaseModel):
    api_key: str = Field(..., min_length=8)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int
    key_name: str | None = None


def _admin_enabled() -> bool:
    """El dashboard admin solo está disponible en modo debug."""
    return settings.app_debug


def _create_session_token(key: ApiKey) -> str:
    """Crea un JWT de sesión para el dashboard."""
    now = datetime.now(UTC)
    expire = now + timedelta(hours=12)
    payload = {
        "sub": key.id,
        "name": key.name,
        "role": "admin",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)  # type: ignore[no-any-return]


def _verify_session_token(
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """Valida el JWT de sesión del dashboard."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload: dict[str, Any] = cast(
            dict[str, Any],
            jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            ),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        ) from None
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        ) from None

    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not an admin token",
        )
    return payload


def _require_admin(payload: dict[str, Any] = Depends(_verify_session_token)) -> dict[str, Any]:
    """Dependency que exige sesión admin válida."""
    return payload


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_db_session() as session:
        yield session


@router.post("/login", response_model=LoginResponse)
async def admin_login(
    login_data: LoginRequest,
    session: AsyncSession = Depends(_get_db),
) -> LoginResponse:
    """Login con la API Key (X-API-Key). Emite JWT de sesión.

    Returns dict with token, token_type, expires_in, key_name
    """
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    key_hash = hashlib.sha256(login_data.api_key.encode()).hexdigest()
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active)
    result = await session.execute(stmt)
    key_obj = result.scalar_one_or_none()

    if not key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    key_obj.last_used_at = datetime.now(UTC)
    await session.flush()
    await session.commit()

    token = _create_session_token(key_obj)
    return LoginResponse(
        token=token,
        token_type="bearer",
        expires_in=12 * 3600,
        key_name=key_obj.name,
    )
