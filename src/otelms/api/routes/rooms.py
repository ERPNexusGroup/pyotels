"""
Room availability endpoints: disponibles / ocupadas / salidas (checkouts).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import (
    get_category_repo,
    get_reservation_repo,
    get_room_repo,
    verify_api_key,
)
from otelms.api.mappers import guest_name as _guest_name
from otelms.api.mappers import room_response as _room_response
from otelms.api.schemas import (
    AvailableRoomsResponse,
    CategoryAvailability,
    CheckoutItem,
    CheckoutsResponse,
    OccupiedRoomItem,
    OccupiedRoomsResponse,
    RoomResponse,
)
from otelms.domain.repositories import (
    CategoryRepository,
    ReservationRepository,
    RoomRepository,
)
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/rooms", tags=["rooms"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=list[RoomResponse])
async def list_rooms(
    hotel_id: str = Query(..., description="Hotel ID"),
    active_only: bool = Query(True, description="Solo habitaciones activas"),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> list[RoomResponse]:
    """Lista habitaciones de un hotel."""
    rooms = await room_repo.get_by_hotel_with_category(hotel_id, active_only=active_only)
    return [_room_response(r) for r in rooms]


@router.get("/available", response_model=AvailableRoomsResponse)
async def get_available_rooms(
    hotel_id: str = Query(..., description="Hotel ID"),
    check_in: date = Query(..., description="Check-in (YYYY-MM-DD)"),
    check_out: date = Query(..., description="Check-out (YYYY-MM-DD)"),
    room_repo: RoomRepository = Depends(get_room_repo),
    category_repo: CategoryRepository = Depends(get_category_repo),
) -> AvailableRoomsResponse:
    """Habitaciones disponibles para un rango de fechas + resumen por categoría."""
    if check_out <= check_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_out debe ser posterior a check_in",
        )

    available = await room_repo.get_available_for_dates(
        hotel_id, check_in.isoformat(), check_out.isoformat()
    )
    all_rooms = await room_repo.get_by_hotel(hotel_id, active_only=True)
    categories = await category_repo.get_by_hotel(hotel_id)
    cat_names = {c.id: (c.name or c.id) for c in categories}

    available_ids = {r.id for r in available}
    total = len(all_rooms)
    occupied_count = total - len(available)

    # Resumen por categoría (sobre habitaciones activas).
    # category_id NULL -> bucket "uncategorized" (consistente con _room_response).
    totals: dict[str, int] = {}
    avail: dict[str, int] = {}
    for room in all_rooms:
        cid = room.category_id or "uncategorized"
        totals[cid] = totals.get(cid, 0) + 1
        if room.id in available_ids:
            avail[cid] = avail.get(cid, 0) + 1

    by_category = [
        CategoryAvailability(
            category_id=cat_id,
            category_name=cat_names.get(cat_id, cat_id),
            total=count,
            available=avail.get(cat_id, 0),
            occupied=count - avail.get(cat_id, 0),
        )
        for cat_id, count in sorted(totals.items())
    ]

    return AvailableRoomsResponse(
        hotel_id=hotel_id,
        check_in=check_in,
        check_out=check_out,
        total_rooms=total,
        available_count=len(available),
        occupied_count=occupied_count,
        occupancy_rate=round(occupied_count / total * 100, 1) if total else 0.0,
        by_category=by_category,
        items=[_room_response(r) for r in available],
    )


@router.get("/occupied", response_model=OccupiedRoomsResponse)
async def get_occupied_rooms(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Fecha a consultar (YYYY-MM-DD)"
    ),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> OccupiedRoomsResponse:
    """Habitaciones ocupadas la noche de una fecha (noches vendidas: status 1 o 2,
    check_in <= fecha < check_out; el día de salida no cuenta)."""
    reservations = await room_repo.get_occupied_for_date(hotel_id, target_date)

    items = [
        OccupiedRoomItem(
            reservation_id=res.id,
            room=_room_response(res.room),
            guest_name=_guest_name(res),
            check_in=res.check_in,
            check_out=res.check_out,
            adults=res.adults or 1,
            children=res.children or 0,
            nights_remaining=max((res.check_out.date() - target_date).days, 0),
        )
        for res in reservations
    ]

    return OccupiedRoomsResponse(
        hotel_id=hotel_id,
        date=target_date,
        occupied_count=len(items),
        items=items,
    )


@router.get("/checkouts", response_model=CheckoutsResponse)
async def get_room_checkouts(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Fecha de salida (YYYY-MM-DD)"
    ),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> CheckoutsResponse:
    """Habitaciones que salen (check-out programado) en una fecha (default hoy)."""
    reservations = await res_repo.get_checkouts_for_date(hotel_id, target_date)

    items = [
        CheckoutItem(
            reservation_id=res.id,
            room=_room_response(res.room),
            guest_name=_guest_name(res),
            check_in=res.check_in,
            check_out=res.check_out,
            adults=res.adults or 1,
            children=res.children or 0,
            total_price=res.total_price,
        )
        for res in reservations
    ]

    return CheckoutsResponse(
        hotel_id=hotel_id,
        date=target_date,
        count=len(items),
        items=items,
    )
