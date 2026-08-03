"""Admin CRM endpoints: tasks for room availability, guests, reservations, notifications."""

import secrets
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import (
    Guest,
    Hotel,
    Reservation,
    Room,
    RoomAvailability,
    SyncLog,
)
from otelms.utils.logging import get_logger

from .auth import _admin_enabled, _get_db, _require_admin

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


# ============================================================
# SCHEMAS
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
