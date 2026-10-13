"""
Room availability endpoints: disponibles / ocupadas / salidas (checkouts).
"""
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import (
    get_category_repo,
    get_category_availability_repo,
    get_channel_rate_repo,
    get_housekeeping_status_repo,
    get_reservation_repo,
    get_room_repo,
    get_room_availability_repo,
    verify_api_key,
)
from otelms.api.mappers import guest_name as _guest_name
from otelms.api.mappers import room_response as _room_response
from otelms.api.schemas import (
    AvailableForSaleByDate,
    AvailableRoomsEnhancedResponse,
    AvailableRoomsResponse,
    AvailableRoomEnhanced,
    CategoryAvailability,
    ChannelRatePerDate,
    CheckoutItem,
    CheckoutsResponse,
    OccupiedRoomItem,
    OccupiedRoomsResponse,
    RoomForSaleItem,
    RoomHousekeepingPerDate,
    RoomRatePerDate,
    RoomResponse,
    RoomsAvailableForSaleResponse,
)
from otelms.domain.repositories import (
    CategoryAvailabilityRepository,
    CategoryRepository,
    ChannelRateRepository,
    HousekeepingStatusRepository,
    ReservationRepository,
    RoomAvailabilityRepository,
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

@router.get("/available/enhanced", response_model=AvailableRoomsEnhancedResponse)
async def get_available_rooms_enhanced(
    hotel_id: str = Query(..., description="Hotel ID"),
    check_in: date = Query(..., description="Check-in (YYYY-MM-DD)"),
    check_out: date = Query(..., description="Check-out (YYYY-MM-DD)"),
    room_repo: RoomRepository = Depends(get_room_repo),
    category_repo: CategoryRepository = Depends(get_category_repo),
    channel_rate_repo: ChannelRateRepository = Depends(get_channel_rate_repo),
    housekeeping_repo: HousekeepingStatusRepository = Depends(get_housekeeping_status_repo),
) -> AvailableRoomsEnhancedResponse:
    """Habitaciones disponibles para un rango de fechas + resumen por categoría + 
    tarifas por canal y estado housekeeping por habitación/fecha."""
    if check_out <= check_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_out debe ser posterior a check_in",
        )

    # Get available rooms (same logic as original)
    available = await room_repo.get_available_for_dates(
        hotel_id, check_in.isoformat(), check_out.isoformat()
    )
    all_rooms = await room_repo.get_by_hotel(hotel_id, active_only=True)
    categories = await category_repo.get_by_hotel(hotel_id)
    cat_names = {c.id: (c.name or c.id) for c in categories}

    available_ids = {r.id for r in available}
    total = len(all_rooms)
    occupied_count = total - len(available)

    # Resumen por categoría
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

    # Build date range for the stay (check_in to check_out - 1)
    date_range = []
    current = check_in
    while current < check_out:
        date_range.append(current)
        current += timedelta(days=1)

    # Get rates for each category in the date range
    rates_by_category: dict[str, dict[date, list[ChannelRatePerDate]]] = {}
    for cat in categories:
        cat_rates = await channel_rate_repo.get_for_availability(
            hotel_id, cat.id, check_in, check_out
        )
        cat_rates_by_date: dict[date, list[ChannelRatePerDate]] = {}
        for r in cat_rates:
            d = r["date"]
            if d not in cat_rates_by_date:
                cat_rates_by_date[d] = []
            cat_rates_by_date[d].append(ChannelRatePerDate(
                channel=r["channel"],
                rate_id=r["rate_id"],
                price=r["price"],
                currency=r["currency"],
                min_stay=r["min_stay"],
            ))
        rates_by_category[cat.id] = cat_rates_by_date

    # Get housekeeping status for available rooms in the date range
    # We need to check status for each available room for each date
    hk_status_by_room: dict[str, dict[date, int]] = {}
    for room in available:
        hk_status_by_room[room.id] = {}
        for d in date_range:
            cleaned_ids = await housekeeping_repo.get_cleaned_room_ids_for_date(hotel_id, d)
            if room.id in cleaned_ids:
                hk_status_by_room[room.id][d] = 2  # cleaned
            else:
                hk_status_by_room[room.id][d] = 0  # pending

    # Build enhanced room responses
    enhanced_rooms = []
    for room in available:
        cat_id = room.category_id or "uncategorized"
        cat_rates_by_date = rates_by_category.get(cat_id, {})
        
        # Build rates_per_date
        rates_per_date = []
        for d in date_range:
            rates = cat_rates_by_date.get(d, [])
            if rates:
                rates_per_date.append(RoomRatePerDate(date=d, rates=rates))
        
        # Build housekeeping_per_date
        housekeeping_per_date = []
        for d in date_range:
            status = hk_status_by_room.get(room.id, {}).get(d, 0)
            status_labels = {0: "pending", 1: "in_progress", 2: "cleaned"}
            housekeeping_per_date.append(RoomHousekeepingPerDate(
                date=d,
                status=status,
                status_label=status_labels.get(status, "pending"),
            ))
        
        enhanced_rooms.append(AvailableRoomEnhanced(
            id=room.id,
            name=room.name,
            category_id=room.category_id or "uncategorized",
            category=_room_response(room).category,
            floor=room.floor,
            max_occupancy=room.max_occupancy,
            is_active=room.is_active,
            rates_per_date=rates_per_date,
            housekeeping_per_date=housekeeping_per_date,
        ))

    return AvailableRoomsEnhancedResponse(
        hotel_id=hotel_id,
        check_in=check_in,
        check_out=check_out,
        total_rooms=total,
        available_count=len(available),
        occupied_count=occupied_count,
        occupancy_rate=round(occupied_count / total * 100, 1) if total else 0.0,
        by_category=by_category,
        items=enhanced_rooms,
        date_range=date_range,
    )


@router.get("/available-for-sale", response_model=RoomsAvailableForSaleResponse)
async def get_rooms_available_for_sale(
    hotel_id: str = Query(..., description="Hotel ID"),
    date_from: date = Query(default_factory=date.today, description="Fecha inicio (YYYY-MM-DD)"),
    date_to: date | None = Query(default=None, description="Fecha fin (YYYY-MM-DD), default date_from + 45 días"),
    channel: str = Query("direct", description="Canal de venta: direct, ota, booking, expedia..."),
    only_cleaned: bool = Query(True, description="Solo habitaciones con estado 'cleaned' en housekeeping"),
    category_id: str | None = Query(None, description="Filtrar por categoría específica"),
    cat_avail_repo: CategoryAvailabilityRepository = Depends(get_category_availability_repo),
    room_repo: RoomRepository = Depends(get_room_repo),
    category_repo: CategoryRepository = Depends(get_category_repo),
    channel_rate_repo: ChannelRateRepository = Depends(get_channel_rate_repo),
    housekeeping_repo: HousekeepingStatusRepository = Depends(get_housekeeping_status_repo),
    room_avail_repo: RoomAvailabilityRepository = Depends(get_room_availability_repo),
) -> RoomsAvailableForSaleResponse:
    """
    Habitaciones disponibles para vender con su tarifa programada.
    
    Usa la disponibilidad que **OtelMS publica en su calendario** (CategoryAvailability.available = calendar_sum),
    no la calculada por reservas. Para cada fecha y categoría, toma las primeras N habitaciones
    (ordenadas por room_name) que no estén bloqueadas manualmente ni sucias.
    """
    if date_to is None:
        date_to = date_from + timedelta(days=45)
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to debe ser posterior o igual a date_from",
        )

    # Get all categories for the hotel
    categories = await category_repo.get_by_hotel(hotel_id)
    if category_id:
        categories = [c for c in categories if c.id == category_id]
        if not categories:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Categoría {category_id} no encontrada para el hotel",
            )

    cat_names = {c.id: (c.name or c.id) for c in categories}
    
    # Build date range
    date_range = []
    current = date_from
    while current <= date_to:
        date_range.append(current)
        current += timedelta(days=1)

    items: list[AvailableForSaleByDate] = []

    for cat in categories:
        # Get all rooms in this category (method only takes category_id, but we filter by hotel_id)
        rooms_in_cat = await room_repo.get_by_category(cat.id)
        # Filter by hotel_id and active status
        rooms_in_cat = [r for r in rooms_in_cat if r.hotel_id == hotel_id and r.is_active]
        room_ids_in_cat = [r.id for r in rooms_in_cat]
        rooms_by_name = sorted(rooms_in_cat, key=lambda r: r.name or r.id)
        
        if not room_ids_in_cat:
            continue

        # Get blocked rooms for this category
        # We need to check for each date separately since blocks can be date-specific
        blocked_by_date: dict[date, tuple[set[str], bool]] = {}
        for d in date_range:
            blocked_specific, has_global = await room_avail_repo.get_blocked_room_ids_for_date(
                hotel_id, d, room_ids_in_cat
            )
            blocked_by_date[d] = (blocked_specific, has_global)

        # Get cleaned room IDs for each date if only_cleaned
        cleaned_by_date: dict[date, set[str]] = {}
        if only_cleaned:
            for d in date_range:
                cleaned_by_date[d] = await housekeeping_repo.get_cleaned_room_ids_for_date(hotel_id, d)

        # Get rates for this category/channel for the date range
        cat_rates = await channel_rate_repo.get_for_availability(
            hotel_id, cat.id, date_from, date_to
        )
        rates_by_date: dict[date, ChannelRateResponse | None] = {}
        for r in cat_rates:
            if r["channel"] == channel:
                d = r["date"]
                # Take the first rate for this channel/date (could be multiple rate_ids)
                if d not in rates_by_date:
                    rates_by_date[d] = ChannelRateResponse(
                        id=f"{hotel_id}-{cat.id}-{r['rate_id']}-{r['channel']}-{r['date']}",
                        hotel_id=hotel_id,
                        category_id=cat.id,
                        rate_id=r["rate_id"],
                        channel=r["channel"],
                        date=r["date"],
                        price=r["price"],
                        currency=r["currency"],
                        min_stay=r.get("min_stay"),
                        created_at=datetime.now(UTC),
                    )

        for d in date_range:
            # Get OtelMS availability for this category/date
            cat_avail_list = await cat_avail_repo.get_range(hotel_id, d, d, cat.id)
            cat_avail = cat_avail_list[0] if cat_avail_list else None
            otelms_available = cat_avail.available if cat_avail else 0
            
            if otelms_available <= 0:
                # No availability according to OtelMS
                items.append(AvailableForSaleByDate(
                    date=d,
                    category_id=cat.id,
                    category_name=cat_names.get(cat.id, cat.id),
                    otelms_available=0,
                    rooms=[],
                ))
                continue

            # Determine blocked rooms for this date
            blocked_specific, has_global_block = blocked_by_date.get(d, (set(), False))
            
            if has_global_block:
                # Global block - all rooms in category are blocked
                items.append(AvailableForSaleByDate(
                    date=d,
                    category_id=cat.id,
                    category_name=cat_names.get(cat.id, cat.id),
                    otelms_available=otelms_available,
                    rooms=[],
                ))
                continue

            # Filter rooms: exclude blocked, and if only_cleaned, exclude dirty
            candidate_rooms = []
            for room in rooms_by_name:
                if room.id in blocked_specific:
                    # Room is specifically blocked
                    continue
                if only_cleaned and room.id not in cleaned_by_date.get(d, set()):
                    # Room is not cleaned and we only want cleaned
                    continue
                candidate_rooms.append(room)

            # Take first N = otelms_available rooms
            available_rooms = candidate_rooms[:otelms_available]

            # Build RoomForSaleItem for each available room
            room_items = []
            rate_for_date = rates_by_date.get(d)
            for room in available_rooms:
                # Determine housekeeping status
                hk_status = "cleaned" if room.id in cleaned_by_date.get(d, set()) else "dirty"
                
                # Check if room has a specific block reason
                blocked_reason = None
                for d2 in date_range:
                    blocked_list, _ = blocked_by_date.get(d2, (set(), False))
                    if room.id in blocked_list:
                        # Find the block record to get reason
                        all_blocks = await room_avail_repo.get_all_for_hotel_date(hotel_id, d2)
                        for blk in all_blocks:
                            if blk.room_id == room.id and blk.is_blocked:
                                blocked_reason = blk.reason
                                break
                        if blocked_reason:
                            break
                
                room_items.append(RoomForSaleItem(
                    room_id=room.id,
                    room_name=room.name,
                    category_id=cat.id,
                    category_name=cat_names.get(cat.id, cat.id),
                    rate=rate_for_date,
                    status=hk_status,
                    blocked_reason=blocked_reason,
                ))

            items.append(AvailableForSaleByDate(
                date=d,
                category_id=cat.id,
                category_name=cat_names.get(cat.id, cat.id),
                otelms_available=otelms_available,
                rooms=room_items,
            ))

    return RoomsAvailableForSaleResponse(
        hotel_id=hotel_id,
        date_from=date_from,
        date_to=date_to,
        channel=channel,
        only_cleaned=only_cleaned,
        items=items,
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
