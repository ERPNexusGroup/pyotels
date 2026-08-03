"""Admin dashboard endpoints: stats, sync logs, manual sync, hotels list/detail."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.config.settings import settings
from otelms.domain.entities import (
    Category,
    Guest,
    Hotel,
    Payment,
    Reservation,
    Room,
    Service,
    SyncLog,
)
from otelms.domain.repositories import HotelRepository
from otelms.services.sync_service import SyncService
from otelms.utils.logging import get_logger

from .auth import _admin_enabled, _get_db, _require_admin

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


class SyncRequest(BaseModel):
    """Payload for manual sync trigger."""
    hotel_id: str
    sync_type: Literal["calendar", "categories", "full", "details"] = "full"
    target_date: str | None = None


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
