"""Admin dashboard endpoints (SOLO en modo debug).

Provee un dashboard web para configurar hoteles y revisar los datos
generados por el scraping. El acceso usa la misma API Key (X-API-Key)
que la API REST como credencial de login, y emite un JWT de sesión.

Seguridad:
- Todo el router se monta solo si settings.app_debug es True.
- El login valida la API Key contra la BD (mismo hash que verify_api_key).
- Las rutas de datos exigen el JWT de sesión emitido en el login.
- La ruta del HTML raíz (/admin) solo existe en debug.
"""

import hashlib
import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Numeric, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select
from starlette.responses import Response

from otelms.config.settings import settings
from otelms.domain.entities import (
    ApiKey,
    Category,
    Guest,
    Hotel,
    Payment,
    Reservation,
    Room,
    RoomAvailability,
    Service,
    SyncLog,
)
from otelms.domain.entities import Base as EntityBase
from otelms.domain.repositories import HotelRepository
from otelms.domain.repositories.database import get_db_session
from otelms.services.sync_service import SyncService
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# ============================================================
# SCHEMAS
# ============================================================

# Dynamic mapping of CRUD slugs to SQLAlchemy model entities
_CRUD_MODELS: dict[str, type[EntityBase]] = {
    "hotels": Hotel,
    "categories": Category,
    "rooms": Room,
    "reservations": Reservation,
    "guests": Guest,
    "api-keys": ApiKey,
}


class RowUpdatePayload(BaseModel):
    """Generic payload for row updates in the admin CRUD."""

    data: dict[str, Any]


# ============================================================
# API KEY SCHEMAS
# ============================================================


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


def _cast_payload_values(model: type[EntityBase], data: dict[str, Any]) -> dict[str, Any]:
    """Cast payload values to appropriate Python types based on SQLAlchemy column types.

    Handles:
    - DateTime: parses ISO format strings to datetime objects
    - Numeric/Decimal: converts strings to Decimal
    - Boolean: ensures proper bool type
    - Others: left as-is
    """
    casted: dict[str, Any] = {}
    for col in model.__table__.columns:
        if col.name in data and data[col.name] is not None:
            val = data[col.name]
            if isinstance(col.type, DateTime) and isinstance(val, str):
                # Handle ISO format strings, including 'Z' suffix
                casted[col.name] = datetime.fromisoformat(val.replace("Z", "+00:00"))
            elif isinstance(col.type, Numeric) and val != "":
                casted[col.name] = Decimal(str(val))
            else:
                casted[col.name] = val
    return casted


class LoginRequest(BaseModel):
    api_key: str = Field(..., min_length=8)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int
    key_name: str | None = None


class SyncRequest(BaseModel):
    hotel_id: str
    sync_type: Literal["calendar", "categories", "full", "details"] = "full"
    target_date: str | None = None


# ============================================================
# HELPERS
# ============================================================


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
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)  # type: ignore[no-any-return]  # jose no tiene stubs; devuelve str


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


# ============================================================
# HTML (login + dashboard SPA)
# ============================================================


@router.get("", include_in_schema=False, response_model=None)
async def admin_page() -> Response:
    """Sirve el dashboard HTML. Solo en debug."""
    if not _admin_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    html_path = _STATIC_DIR / "admin.html"
    if not html_path.exists():
        return JSONResponse(status_code=500, content={"detail": "admin.html missing"})
    return FileResponse(html_path, media_type="text/html")


# ============================================================
# AUTH
# ============================================================


@router.post("/login", response_model=LoginResponse)
async def admin_login(
    login_data: LoginRequest,
    session: AsyncSession = Depends(_get_db),
) -> LoginResponse:
    """Login con la API Key (X-API-Key). Emite JWT de sesión."""
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
        expires_in=12 * 3600,
        key_name=key_obj.name,
    )


# ============================================================
# DATA ENDPOINTS (requieren sesión admin)
# ============================================================


@router.get("/api/stats")
async def admin_stats(
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Estadísticas generales: conteos por entidad y último sync."""
    counts: dict[str, int] = {}

    for name, model in [
        ("hotels", Hotel),
        ("categories", Category),
        ("rooms", Room),
        ("reservations", Reservation),
        ("guests", Guest),
        ("sync_logs", SyncLog),
    ]:
        count_result = await session.execute(select(func.count()).select_from(model))
        counts[name] = int(count_result.scalar_one())

    # Últimos sync logs
    logs_stmt = select(SyncLog).order_by(SyncLog.started_at.desc()).limit(10)
    logs_result = await session.execute(logs_stmt)
    recent_logs = logs_result.scalars().all()

    return {
        "counts": counts,
        "recent_syncs": [
            {
                "id": log.id,
                "hotel_id": log.hotel_id,
                "sync_type": log.sync_type,
                "status": log.status,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "duration_ms": log.duration_ms,
                "records_created": log.records_created,
                "records_updated": log.records_updated,
                "error_count": log.error_count,
            }
            for log in recent_logs
        ],
        "app": {
            "env": settings.app_env,
            "debug": settings.app_debug,
            "version": "1.0.0",
        },
    }


@router.get("/api/hotels")
async def admin_hotels(
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Lista hoteles con métricas de sync (sin contraseñas)."""
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


@router.get("/api/hotels/{hotel_id}/detail")
async def admin_hotel_detail(
    hotel_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Get hotel detail with counts of all related entities."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Fetch hotel
    stmt = select(Hotel).where(Hotel.id == hotel_id)
    result = await session.execute(stmt)
    hotel = result.scalar_one_or_none()

    if not hotel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotel not found")

    # Count categories
    categories_result = await session.execute(
        select(func.count()).select_from(Category).where(Category.hotel_id == hotel_id)
    )
    categories_count = int(categories_result.scalar_one())

    # Count rooms
    rooms_result = await session.execute(select(func.count()).select_from(Room).where(Room.hotel_id == hotel_id))
    rooms_count = int(rooms_result.scalar_one())

    # Count reservations
    reservations_result = await session.execute(
        select(func.count()).select_from(Reservation).where(Reservation.hotel_id == hotel_id)
    )
    reservations_count = int(reservations_result.scalar_one())

    # Count guests
    guests_result = await session.execute(select(func.count()).select_from(Guest).where(Guest.hotel_id == hotel_id))
    guests_count = int(guests_result.scalar_one())

    # Count sync_logs
    sync_logs_result = await session.execute(
        select(func.count()).select_from(SyncLog).where(SyncLog.hotel_id == hotel_id)
    )
    sync_logs_count = int(sync_logs_result.scalar_one())

    # Count payments (via reservations)
    payments_result = await session.execute(
        select(func.count(Payment.id))
        .join(Reservation, Payment.reservation_id == Reservation.id)
        .where(Reservation.hotel_id == hotel_id)
    )
    payments_count = int(payments_result.scalar_one())

    # Count services (via reservations)
    services_result = await session.execute(
        select(func.count(Service.id))
        .join(Reservation, Service.reservation_id == Reservation.id)
        .where(Reservation.hotel_id == hotel_id)
    )
    services_count = int(services_result.scalar_one())

    # Build sub-tables metadata for UI
    sub_tables = [
        {"slug": "categories", "label": "Categories", "count": categories_count},
        {"slug": "rooms", "label": "Rooms", "count": rooms_count},
        {"slug": "reservations", "label": "Reservations", "count": reservations_count},
        {"slug": "guests", "label": "Guests", "count": guests_count},
        {"slug": "payments", "label": "Payments", "count": payments_count},
        {"slug": "services", "label": "Services", "count": services_count},
        {"slug": "sync_logs", "label": "Sync Logs", "count": sync_logs_count},
    ]

    return {
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
        "created_at": hotel.created_at.isoformat() if hotel.created_at else None,
        "updated_at": hotel.updated_at.isoformat() if hotel.updated_at else None,
        "last_sync_at": hotel.last_sync_at.isoformat() if hotel.last_sync_at else None,
        "counts": {
            "categories": categories_count,
            "rooms": rooms_count,
            "reservations": reservations_count,
            "guests": guests_count,
            "payments": payments_count,
            "services": services_count,
            "sync_logs": sync_logs_count,
        },
        "sub_tables": sub_tables,
    }


@router.get("/api/sync-logs")
async def admin_sync_logs(
    hotel_id: str | None = None,
    sync_type: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Historial de sync logs con filtros."""
    limit = max(1, min(limit, 200))

    stmt = select(SyncLog)
    if hotel_id:
        stmt = stmt.where(SyncLog.hotel_id == hotel_id)
    if sync_type:
        stmt = stmt.where(SyncLog.sync_type == sync_type)
    if status_filter:
        stmt = stmt.where(SyncLog.status == status_filter)
    stmt = stmt.order_by(SyncLog.started_at.desc()).limit(limit)

    result = await session.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "hotel_id": log.hotel_id,
            "sync_type": log.sync_type,
            "status": log.status,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "completed_at": log.completed_at.isoformat() if log.completed_at else None,
            "duration_ms": log.duration_ms,
            "records_processed": log.records_processed,
            "records_created": log.records_created,
            "records_updated": log.records_updated,
            "error_count": log.error_count,
            "errors": log.errors,
        }
        for log in logs
    ]


@router.get("/api/config")
async def admin_config(
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Configuración relevante del scraper (solo debug)."""
    return {
        "app_env": settings.app_env,
        "app_debug": settings.app_debug,
        "database_url": settings.database_url,
        "redis_url": settings.redis_url,
        "celery_broker_url": settings.celery_broker_url,
        "scraper": {
            "headless": settings.scraper_headless,
            "base_domain": settings.otelms_base_domain,
            "default_hotel_id": settings.otelms_default_hotel_id,
            "timeout_ms": settings.scraper_timeout_ms,
            "navigation_timeout_ms": settings.scraper_navigation_timeout_ms,
            "selector_timeout_ms": settings.scraper_selector_timeout_ms,
        },
        "jwt": {
            "algorithm": settings.jwt_algorithm,
            "access_token_expire_minutes": settings.jwt_access_token_expire_minutes,
        },
    }


@router.post("/api/sync")
async def admin_trigger_sync(
    sync_request: SyncRequest,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Triggea una sincronización manual para un hotel."""
    hotel_repo = HotelRepository(session)
    hotel = await hotel_repo.get_by_id(sync_request.hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel {sync_request.hotel_id} not found",
        )

    service = await SyncService.from_hotel(hotel)

    try:
        await service.initialize()
        if sync_request.sync_type == "calendar":
            result = await service.sync_calendar(sync_request.target_date)
        elif sync_request.sync_type == "categories":
            result = await service.sync_categories(sync_request.target_date)
        elif sync_request.sync_type == "details":
            result = await service.sync_reservation_details(
                sync_request.target_date or datetime.now(UTC).strftime("%Y-%m-%d")
            )
        else:
            result = await service.full_sync(sync_request.target_date)
    except Exception as exc:
        # Errores de auth/red del scraper NO deben ser 500; se reportan como fallo controlado
        logger.error("Manual sync failed", hotel_id=sync_request.hotel_id, error=str(exc))
        return {
            "operation": sync_request.sync_type,
            "success": False,
            "duration_ms": None,
            "records_created": 0,
            "records_updated": 0,
            "errors": [str(exc)],
            "completed_at": None,
        }
    finally:
        await service.close()

    return {
        "operation": result.operation,
        "success": result.success,
        "duration_ms": result.duration_ms,
        "records_created": result.records_created,
        "records_updated": result.records_updated,
        "errors": result.errors,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
    }


# ============================================================
# DYNAMIC CRUD ENDPOINTS
# ============================================================


@router.get("/api/tables/{table_slug}")
async def list_table_rows(
    table_slug: str,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """List rows for a dynamic table with pagination."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model: type[EntityBase] = _CRUD_MODELS[table_slug]

    # Dynamic select
    stmt: Select[tuple[EntityBase]] = select(model).offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Serialize to dict of attributes
    serialized = []
    for row in rows:
        serialized.append({c.name: getattr(row, c.name) for c in model.__table__.columns})

    return {
        "columns": [c.name for c in model.__table__.columns],
        "rows": serialized,
    }


@router.get("/api/tables/{table_slug}/{id}")
async def get_table_row(
    table_slug: str,
    id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Get a single row by ID for a dynamic table."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model: type[EntityBase] = _CRUD_MODELS[table_slug]

    stmt: Select[tuple[EntityBase]] = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


@router.post("/api/tables/{table_slug}", status_code=status.HTTP_201_CREATED)
async def create_table_row(
    table_slug: str,
    payload: RowUpdatePayload,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Create a new row in a dynamic table."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model: type[EntityBase] = _CRUD_MODELS[table_slug]

    # Cast and validate payload values
    casted_data = _cast_payload_values(model, payload.data)

    # Create new instance
    new_row = model(**casted_data)
    session.add(new_row)
    await session.flush()
    await session.commit()
    await session.refresh(new_row)

    # Return serialized row
    return {c.name: getattr(new_row, c.name) for c in model.__table__.columns}


@router.put("/api/tables/{table_slug}/{id}")
async def update_table_row(
    table_slug: str,
    id: str,
    payload: RowUpdatePayload,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Update an existing row in a dynamic table."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model: type[EntityBase] = _CRUD_MODELS[table_slug]

    # Fetch existing row
    stmt: Select[tuple[EntityBase]] = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    # Cast and validate payload values
    casted_data = _cast_payload_values(model, payload.data)

    # Update only provided fields
    for field_name, value in casted_data.items():
        setattr(row, field_name, value)

    await session.flush()
    await session.commit()
    await session.refresh(row)

    # Return serialized row
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


@router.delete("/api/tables/{table_slug}/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table_row(
    table_slug: str,
    id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> None:
    """Delete a row from a dynamic table."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model: type[EntityBase] = _CRUD_MODELS[table_slug]

    # Fetch existing row
    stmt: Select[tuple[EntityBase]] = select(model).where(model.id == id)  # type: ignore[attr-defined]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Row not found")

    # Delete row
    await session.delete(row)
    await session.commit()


# ============================================================
# API KEYS CRUD ENDPOINTS
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

    # Update only provided fields
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


# ============================================================
# TASKS ENDPOINTS (Date-based room availability operations)
# ============================================================


class CloseDatesRequest(BaseModel):
    """Payload for closing room dates (blocking availability)."""

    hotel_id: str
    room_ids: list[str] = Field(default_factory=list)  # Empty = all rooms in hotel
    start_date: datetime
    end_date: datetime
    reason: str | None = None


class OpenDatesRequest(BaseModel):
    """Payload for opening room dates (unblocking availability)."""

    hotel_id: str
    room_ids: list[str] = Field(default_factory=list)  # Empty = all rooms in hotel
    start_date: datetime
    end_date: datetime


class MoveReservationRequest(BaseModel):
    """Payload for moving a reservation to a different room."""

    reservation_id: str
    new_room_id: str


class AvailabilityResponse(BaseModel):
    """Response model for room availability exceptions."""

    id: str
    hotel_id: str
    room_id: str | None
    room_name: str | None
    start_date: datetime
    end_date: datetime
    is_blocked: bool
    reason: str | None
    created_at: datetime


class GuestInfoResponse(BaseModel):
    """Response model for guest info in tasks."""

    id: str
    hotel_id: str
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    document_type: str | None
    document_number: str | None
    nationality: str | None
    created_at: datetime


class ReservationInfoResponse(BaseModel):
    """Response model for reservation info in tasks."""

    id: str
    hotel_id: str
    room_id: str
    room_name: str | None
    guest_id: str | None
    guest_name: str | None
    check_in: datetime
    check_out: datetime
    status: int
    adults: int
    children: int
    babies: int
    total_price: Decimal | None
    currency: str
    source: str | None
    created_at: datetime


class NotificationResponse(BaseModel):
    """Response model for system notifications."""

    id: str
    type: str  # "sync_error", "sync_failed", "high_error_rate", etc.
    hotel_id: str | None
    message: str
    severity: str  # "error", "warning", "info"
    created_at: datetime
    is_read: bool


# ============================================================
# TASKS ENDPOINTS
# ============================================================


@router.post("/api/tasks/close-dates")
async def close_dates(
    payload: CloseDatesRequest,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Block rooms for a date range (close availability)."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Validate hotel exists
    hotel_stmt = select(Hotel).where(Hotel.id == payload.hotel_id)
    hotel_result = await session.execute(hotel_stmt)
    hotel = hotel_result.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")

    # Determine target rooms
    if payload.room_ids:
        rooms_stmt = select(Room).where(Room.id.in_(payload.room_ids), Room.hotel_id == payload.hotel_id)
        rooms_result = await session.execute(rooms_stmt)
        rooms = rooms_result.scalars().all()
        if len(rooms) != len(payload.room_ids):
            raise HTTPException(status_code=400, detail="Some room IDs not found in this hotel")
    else:
        # All rooms in hotel
        rooms_stmt = select(Room).where(Room.hotel_id == payload.hotel_id)
        rooms_result = await session.execute(rooms_stmt)
        rooms = rooms_result.scalars().all()

    created_count = 0
    for room in rooms:
        # For now, just create new record (in production, you might want to merge overlapping ranges)
        avail = RoomAvailability(
            id=secrets.token_urlsafe(16),
            hotel_id=payload.hotel_id,
            room_id=room.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_blocked=True,
            reason=payload.reason or "blocked",
        )
        session.add(avail)
        created_count += 1

    await session.commit()
    return {
        "success": True,
        "message": f"Blocked {created_count} rooms from {payload.start_date.date()} to {payload.end_date.date()}",
        "rooms_blocked": created_count,
    }


@router.post("/api/tasks/open-dates")
async def open_dates(
    payload: OpenDatesRequest,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Unblock rooms for a date range (open availability)."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Validate hotel exists
    hotel_stmt = select(Hotel).where(Hotel.id == payload.hotel_id)
    hotel_result = await session.execute(hotel_stmt)
    hotel = hotel_result.scalar_one_or_none()
    if not hotel:
        raise HTTPException(status_code=404, detail="Hotel not found")

    # Determine target rooms
    if payload.room_ids:
        rooms_stmt = select(Room).where(Room.id.in_(payload.room_ids), Room.hotel_id == payload.hotel_id)
        rooms_result = await session.execute(rooms_stmt)
        rooms = rooms_result.scalars().all()
        if len(rooms) != len(payload.room_ids):
            raise HTTPException(status_code=400, detail="Some room IDs not found in this hotel")
    else:
        # All rooms in hotel
        rooms_stmt = select(Room).where(Room.hotel_id == payload.hotel_id)
        rooms_result = await session.execute(rooms_stmt)
        rooms = rooms_result.scalars().all()

    opened_count = 0
    for room in rooms:
        # Find and delete blocking records that overlap with the range
        overlap_stmt = select(RoomAvailability).where(
            RoomAvailability.room_id == room.id,
            RoomAvailability.start_date <= payload.end_date,
            RoomAvailability.end_date >= payload.start_date,
            RoomAvailability.is_blocked.is_(True),
        )
        overlap_result = await session.execute(overlap_stmt)
        overlaps = overlap_result.scalars().all()

        for overlap in overlaps:
            await session.delete(overlap)
            opened_count += 1

        # If we want to explicitly mark as open (not just delete), create is_blocked=False records
        # For now, deletion is sufficient

    await session.commit()
    return {
        "success": True,
        "message": f"Opened {opened_count} rooms from {payload.start_date.date()} to {payload.end_date.date()}",
        "rooms_opened": opened_count,
    }


@router.get("/api/tasks/availability", response_model=list[AvailabilityResponse])
async def list_availability(
    hotel_id: str | None = None,
    room_id: str | None = None,
    is_blocked: bool | None = None,
    start_from: datetime | None = None,
    end_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[AvailabilityResponse]:
    """List room availability exceptions with filters."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = (
        select(RoomAvailability, Room.name.label("room_name"))
        .outerjoin(Room, RoomAvailability.room_id == Room.id)
    )

    if hotel_id:
        stmt = stmt.where(RoomAvailability.hotel_id == hotel_id)
    if room_id:
        stmt = stmt.where(RoomAvailability.room_id == room_id)
    if is_blocked is not None:
        stmt = stmt.where(RoomAvailability.is_blocked == is_blocked)
    if start_from:
        stmt = stmt.where(RoomAvailability.start_date >= start_from)
    if end_before:
        stmt = stmt.where(RoomAvailability.end_date <= end_before)

    stmt = stmt.order_by(RoomAvailability.start_date.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    return [
        AvailabilityResponse(
            id=avail.id,
            hotel_id=avail.hotel_id,
            room_id=avail.room_id,
            room_name=room_name,
            start_date=avail.start_date,
            end_date=avail.end_date,
            is_blocked=avail.is_blocked,
            reason=avail.reason,
            created_at=avail.created_at,
        )
        for avail, room_name in rows
    ]


@router.get("/api/tasks/guests", response_model=list[GuestInfoResponse])
async def list_guests(
    hotel_id: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[GuestInfoResponse]:
    """List guests with pagination and search."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(Guest)
    if hotel_id:
        stmt = stmt.where(Guest.hotel_id == hotel_id)
    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            (Guest.first_name.ilike(search_term))
            | (Guest.last_name.ilike(search_term))
            | (Guest.email.ilike(search_term))
            | (Guest.document_number.ilike(search_term))
        )

    stmt = stmt.order_by(Guest.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    guests = result.scalars().all()

    return [
        GuestInfoResponse(
            id=g.id,
            hotel_id=g.hotel_id,
            first_name=g.first_name,
            last_name=g.last_name,
            email=g.email,
            phone=g.phone,
            document_type=g.document_type,
            document_number=g.document_number,
            nationality=g.nationality,
            created_at=g.created_at,
        )
        for g in guests
    ]


@router.get("/api/tasks/reservations", response_model=list[ReservationInfoResponse])
async def list_reservations(
    hotel_id: str | None = None,
    room_id: str | None = None,
    reservation_status: int | None = None,
    check_in_from: datetime | None = None,
    check_out_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[ReservationInfoResponse]:
    """List reservations with filters."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = (
        select(Reservation, Room.name.label("room_name"), Guest.first_name, Guest.last_name)
        .outerjoin(Room, Reservation.room_id == Room.id)
        .outerjoin(Guest, Reservation.guest_id == Guest.id)
    )

    if hotel_id:
        stmt = stmt.where(Reservation.hotel_id == hotel_id)
    if room_id:
        stmt = stmt.where(Reservation.room_id == room_id)
    if reservation_status is not None:
        stmt = stmt.where(Reservation.status == reservation_status)
    if check_in_from:
        stmt = stmt.where(Reservation.check_in >= check_in_from)
    if check_out_before:
        stmt = stmt.where(Reservation.check_out <= check_out_before)

    stmt = stmt.order_by(Reservation.check_in.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    return [
        ReservationInfoResponse(
            id=r.id,
            hotel_id=r.hotel_id,
            room_id=r.room_id,
            room_name=room_name,
            guest_id=r.guest_id,
            guest_name=(f"{fn} {ln}".strip() if fn or ln else None) if (fn := first_name) or (ln := last_name) else None,
            check_in=r.check_in,
            check_out=r.check_out,
            status=r.status,
            adults=r.adults,
            children=r.children,
            babies=r.babies,
            total_price=r.total_price,
            currency=r.currency,
            source=r.source,
            created_at=r.created_at,
        )
        for r, room_name, first_name, last_name in rows
    ]


@router.post("/api/tasks/move-reservation")
async def move_reservation(
    payload: MoveReservationRequest,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Move a reservation to a different room."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Get reservation
    res_stmt = select(Reservation).where(Reservation.id == payload.reservation_id)
    res_result = await session.execute(res_stmt)
    reservation = res_result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    # Get new room
    room_stmt = select(Room).where(Room.id == payload.new_room_id, Room.hotel_id == reservation.hotel_id)
    room_result = await session.execute(room_stmt)
    new_room = room_result.scalar_one_or_none()
    if not new_room:
        raise HTTPException(status_code=404, detail="Target room not found in same hotel")

    # Check for conflicts in new room for the same dates
    conflict_stmt = select(Reservation).where(
        Reservation.room_id == payload.new_room_id,
        Reservation.id != payload.reservation_id,
        Reservation.status.in_([1, 2]),  # Reservation or Check-in
        Reservation.check_in < reservation.check_out,
        Reservation.check_out > reservation.check_in,
    )
    conflict_result = await session.execute(conflict_stmt)
    conflict = conflict_result.scalar_one_or_none()
    if conflict:
        raise HTTPException(status_code=400, detail="Room not available for those dates")

    old_room_id = reservation.room_id
    reservation.room_id = payload.new_room_id
    await session.flush()
    await session.commit()

    return {
        "success": True,
        "message": f"Reservation moved from room {old_room_id} to {payload.new_room_id}",
        "reservation_id": payload.reservation_id,
        "old_room_id": old_room_id,
        "new_room_id": payload.new_room_id,
    }


@router.get("/api/tasks/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    hotel_id: str | None = None,
    severity: str | None = None,
    is_read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[NotificationResponse]:
    """List system notifications (sync errors, failed syncs, high error rates)."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    # Build notifications from sync logs
    # This is a dynamic computation - in production you'd have a notifications table
    stmt = select(SyncLog)
    if hotel_id:
        stmt = stmt.where(SyncLog.hotel_id == hotel_id)
    stmt = stmt.where(SyncLog.status.in_(["failed", "started"])).order_by(SyncLog.started_at.desc()).limit(200)

    result = await session.execute(stmt)
    logs = result.scalars().all()

    notifications = []
    for log in logs:
        # Determine severity based on status
        if log.status == "failed":
            sev = "error"
            msg = f"Sync failed: {log.sync_type} for hotel {log.hotel_id}"
            if log.errors:
                msg += f" - {log.errors[0]}"
        elif log.status == "started":
            sev = "info"
            msg = f"Sync started: {log.sync_type} for hotel {log.hotel_id}"
        else:
            sev = "info"
            msg = f"Sync {log.status}: {log.sync_type} for hotel {log.hotel_id}"

        notifications.append(
            NotificationResponse(
                id=f"sync_{log.id}",
                type="sync_" + log.status,
                hotel_id=log.hotel_id,
                message=msg,
                severity=sev,
                created_at=log.started_at or log.completed_at or datetime.now(UTC),
                is_read=False,  # In production, track read status in DB
            )
        )

    # Filter by severity if requested
    if severity:
        notifications = [n for n in notifications if n.severity == severity]

    # Paginate
    total = len(notifications)
    start = min(offset, total)
    end = min(start + limit, total)

    return notifications[start:end]
