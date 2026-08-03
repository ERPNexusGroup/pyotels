"""Admin config endpoints: hotels CRUD, API keys CRUD, system settings."""

import hashlib
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import (
    ApiKey,
    Hotel,
    SyncLog,
)
from otelms.utils.crypto import credential_encryption
from otelms.utils.logging import get_logger

from .auth import _admin_enabled, _get_db, _require_admin

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


# ============================================================
# SCHEMAS
# ============================================================


class HotelCreate(BaseModel):
    """Payload for creating a new hotel."""

    id: str
    name: str | None = None
    domain: str = "otelms.com"
    username: str
    password: str
    is_active: bool = True


class HotelUpdate(BaseModel):
    """Payload for updating a hotel."""

    name: str | None = None
    domain: str | None = None
    username: str | None = None
    password: str | None = None
    is_active: bool | None = None
    scraper_rate_limit_rpm: int | None = None
    scraper_burst: int | None = None
    scraper_timeout_ms: int | None = None
    scraper_navigation_timeout_ms: int | None = None
    scraper_selector_timeout_ms: int | None = None
    custom_domain: str | None = None
    use_custom_domain: bool | None = None
    scraper_headless: bool | None = None


class HotelResponse(BaseModel):
    """Response model for hotel (without password)."""

    id: str
    name: str | None
    domain: str
    custom_domain: str | None
    use_custom_domain: bool
    username: str
    is_active: bool
    scraper_headless: bool
    scraper_rate_limit_rpm: int
    scraper_burst: int
    scraper_timeout_ms: int
    scraper_navigation_timeout_ms: int
    scraper_selector_timeout_ms: int
    created_at: datetime
    updated_at: datetime
    last_sync_at: datetime | None

    class Config:
        from_attributes = True


class ApiKeyCreate(BaseModel):
    """Payload for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=100)
    rate_limit: int = Field(default=60, ge=1, le=10000)
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    """Payload for updating an API key."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    rate_limit: int | None = Field(default=None, ge=1, le=10000)
    is_active: bool | None = None
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    """Response model for API key (without the key hash)."""

    id: str
    name: str
    is_active: bool
    rate_limit: int
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


class ApiKeyCreateResponse(ApiKeyResponse):
    """Response model for API key creation (includes the plain key - shown once)."""

    key: str


# ============================================================
# HOTELS CRUD
# ============================================================


@router.get("/api/config/hotels")
async def config_list_hotels(
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Lista hoteles con métricas de sync (para configuración)."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(Hotel).order_by(Hotel.id)
    result = await session.execute(stmt)
    hotels = result.scalars().all()

    out: list[dict[str, Any]] = []
    for hotel in hotels:
        sync_result = await session.execute(
            select(
                func.count(SyncLog.id),
                func.count().filter(SyncLog.status == "completed"),
                func.count().filter(SyncLog.status == "failed"),
            ).where(SyncLog.hotel_id == hotel.id)
        )
        total_logs, completed, failed = sync_result.one()

        last_stmt = select(SyncLog).where(SyncLog.hotel_id == hotel.id).order_by(SyncLog.started_at.desc()).limit(1)
        last_result = await session.execute(last_stmt)
        last_log = last_result.scalar_one_or_none()

        out.append(
            {
                "id": hotel.id,
                "name": hotel.name,
                "domain": hotel.domain,
                "custom_domain": hotel.custom_domain,
                "use_custom_domain": hotel.use_custom_domain,
                "username": hotel.username,
                "is_active": hotel.is_active,
                "scraper_headless": hotel.scraper_headless,
                "scraper_rate_limit_rpm": hotel.scraper_rate_limit_rpm,
                "scraper_burst": hotel.scraper_burst,
                "scraper_timeout_ms": hotel.scraper_timeout_ms,
                "scraper_navigation_timeout_ms": hotel.scraper_navigation_timeout_ms,
                "scraper_selector_timeout_ms": hotel.scraper_selector_timeout_ms,
                "sync": {
                    "total": int(total_logs),
                    "completed": int(completed),
                    "failed": int(failed),
                    "last_status": last_log.status if last_log else None,
                    "last_started_at": last_log.started_at.isoformat() if last_log and last_log.started_at else None,
                },
            }
        )
    return out


@router.get("/api/config/hotels/{hotel_id}")
async def config_get_hotel(
    hotel_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> HotelResponse:
    """Obtiene un hotel por ID."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(Hotel).where(Hotel.id == hotel_id)
    result = await session.execute(stmt)
    hotel = result.scalar_one_or_none()

    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found")

    return HotelResponse.model_validate(hotel)


@router.post("/api/config/hotels", status_code=status.HTTP_201_CREATED)
async def config_create_hotel(
    payload: HotelCreate,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> HotelResponse:
    """Crea un nuevo hotel."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Check if ID exists
    existing = await session.execute(select(Hotel).where(Hotel.id == payload.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Hotel ID already exists")

    # Hash password for login verification
    password_hash = hashlib.sha256(payload.password.encode()).hexdigest()

    # Encrypt password for scraper (Fernet)
    encrypted_password = credential_encryption.encrypt(payload.password)

    new_hotel = Hotel(
        id=payload.id,
        name=payload.name,
        domain=payload.domain,
        username=payload.username,
        password_hash=password_hash,
        encrypted_password=encrypted_password,
        is_active=payload.is_active,
    )
    session.add(new_hotel)
    await session.flush()
    await session.commit()
    await session.refresh(new_hotel)

    return HotelResponse.model_validate(new_hotel)


@router.put("/api/config/hotels/{hotel_id}")
async def config_update_hotel(
    hotel_id: str,
    payload: HotelUpdate,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> HotelResponse:
    """Actualiza un hotel."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(Hotel).where(Hotel.id == hotel_id)
    result = await session.execute(stmt)
    hotel = result.scalar_one_or_none()

    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Handle password separately
    if "password" in update_data:
        password = update_data.pop("password")
        hotel.password_hash = hashlib.sha256(password.encode()).hexdigest()
        hotel.encrypted_password = credential_encryption.encrypt(password)

    for field_name, value in update_data.items():
        setattr(hotel, field_name, value)

    await session.flush()
    await session.commit()
    await session.refresh(hotel)

    return HotelResponse.model_validate(hotel)


@router.delete("/api/config/hotels/{hotel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def config_delete_hotel(
    hotel_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> None:
    """Elimina un hotel."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(Hotel).where(Hotel.id == hotel_id)
    result = await session.execute(stmt)
    hotel = result.scalar_one_or_none()

    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found")

    await session.delete(hotel)
    await session.commit()


# ============================================================
# API KEYS CRUD
# ============================================================


@router.get("/api/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[ApiKeyResponse]:
    """List API keys with pagination."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(ApiKey).order_by(ApiKey.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    keys = result.scalars().all()

    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            is_active=key.is_active,
            rate_limit=key.rate_limit,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            expires_at=key.expires_at,
        )
        for key in keys
    ]


@router.get("/api/api-keys/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(
    key_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> ApiKeyResponse:
    """Get a single API key by ID."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(ApiKey).where(ApiKey.id == key_id)
    result = await session.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        is_active=key.is_active,
        rate_limit=key.rate_limit,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )


@router.post("/api/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the plain key only once."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Generate a secure random API key
    plain_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(plain_key.encode()).hexdigest()

    # Generate unique ID
    key_id = secrets.token_urlsafe(16)

    new_key = ApiKey(
        id=key_id,
        name=payload.name,
        key_hash=key_hash,
        is_active=True,
        rate_limit=payload.rate_limit,
        expires_at=payload.expires_at,
    )
    session.add(new_key)
    await session.flush()
    await session.commit()
    await session.refresh(new_key)

    return ApiKeyCreateResponse(
        id=new_key.id,
        name=new_key.name,
        is_active=new_key.is_active,
        rate_limit=new_key.rate_limit,
        created_at=new_key.created_at,
        last_used_at=new_key.last_used_at,
        expires_at=new_key.expires_at,
        key=plain_key,
    )


@router.put("/api/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: str,
    payload: ApiKeyUpdate,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> ApiKeyResponse:
    """Update an API key (name, rate_limit, is_active, expires_at)."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(ApiKey).where(ApiKey.id == key_id)
    result = await session.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(key, field_name, value)

    await session.flush()
    await session.commit()
    await session.refresh(key)

    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        is_active=key.is_active,
        rate_limit=key.rate_limit,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )


@router.patch("/api/api-keys/{key_id}/toggle", response_model=ApiKeyResponse)
async def toggle_api_key(
    key_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> ApiKeyResponse:
    """Toggle the is_active status of an API key."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(ApiKey).where(ApiKey.id == key_id)
    result = await session.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = not key.is_active

    await session.flush()
    await session.commit()
    await session.refresh(key)

    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        is_active=key.is_active,
        rate_limit=key.rate_limit,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )


@router.delete("/api/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> None:
    """Delete an API key."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(ApiKey).where(ApiKey.id == key_id)
    result = await session.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await session.delete(key)
    await session.commit()
