"""Admin calendar endpoints: room status, categories, notifications overview."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import (
    Category,
    Room,
    RoomAvailability,
    SyncLog,
)
from otelms.utils.logging import get_logger

from .auth import _admin_enabled, _get_db, _require_admin

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


@router.get("/api/calendar/room-status")
async def calendar_room_status(
    hotel_id: str,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    """Get room status grid for calendar view."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Default to current month
    if not start_date:
        start_date = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if not end_date:
        # Next month
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1)

    # Get rooms for hotel
    rooms_stmt = select(Room).where(Room.hotel_id == hotel_id, Room.is_active.is_(True))
    rooms_result = await session.execute(rooms_stmt)
    rooms = rooms_result.scalars().all()

    # Get availability exceptions for date range
    avail_stmt = select(RoomAvailability).where(
        RoomAvailability.hotel_id == hotel_id,
        RoomAvailability.start_date < end_date,
        RoomAvailability.end_date >= start_date,
    )
    avail_result = await session.execute(avail_stmt)
    availabilities = avail_result.scalars().all()

    # Build status grid
    room_status = {}
    for room in rooms:
        room_avail = [a for a in availabilities if a.room_id == room.id]
        room_status[room.id] = {
            "room_name": room.name,
            "category_id": room.category_id,
            "exceptions": [
                {
                    "start_date": a.start_date.isoformat(),
                    "end_date": a.end_date.isoformat(),
                    "is_blocked": a.is_blocked,
                    "reason": a.reason,
                }
                for a in room_avail
            ],
        }

    return {
        "hotel_id": hotel_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rooms": room_status,
    }


@router.get("/api/calendar/categories")
async def calendar_categories(
    hotel_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Get categories for calendar filtering."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(Category).where(Category.hotel_id == hotel_id).order_by(Category.sort_order)
    result = await session.execute(stmt)
    categories = result.scalars().all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "sort_order": c.sort_order,
        }
        for c in categories
    ]


@router.get("/api/calendar/notifications")
async def calendar_notifications(
    hotel_id: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> list[dict[str, Any]]:
    """Get recent sync notifications for calendar view."""
    if not _admin_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    stmt = select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit)
    if hotel_id:
        stmt = stmt.where(SyncLog.hotel_id == hotel_id)

    result = await session.execute(stmt)
    logs = result.scalars().all()

    notifications = []
    for log in logs:
        if log.status == "failed":
            sev = "error"
            msg = f"Sync failed: {log.sync_type}"
        elif log.status == "started":
            sev = "info"
            msg = f"Sync started: {log.sync_type}"
        else:
            sev = "info"
            msg = f"Sync {log.status}: {log.sync_type}"

        notifications.append(
            {
                "id": f"sync_{log.id}",
                "type": "sync_" + log.status,
                "hotel_id": log.hotel_id,
                "message": msg,
                "severity": sev,
                "created_at": log.started_at.isoformat() if log.started_at else None,
            }
        )

    return notifications
