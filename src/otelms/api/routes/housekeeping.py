"""
Housekeeping endpoints - Limpieza de habitaciones.

Criterio:
- "limpieza completa" (full): habitaciones con check-out hoy (el huésped se fue, limpieza profunda)
- "limpieza continua" (continuous): habitaciones que pernoctan esa noche (el huésped sigue, limpieza ligera)
- "bloqueadas" (blocked): habitaciones sin reserva activa para la fecha
- "ingresos" (income_generating): habitaciones con reserva futura que generara ingresos

Issue 3: Actualización de estado de limpieza por habitación.
- PATCH /{room_id}  → cambiar estado (requiere permiso housekeeping:write)
- POST /reset      → reiniciar todos a pending (requiere housekeeping:write)
- GET (existente)  → lista filtrando exclude cleaned (requiere housekeeping:read)
"""
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import (
    get_db,
    get_housekeeping_status_repo,
    get_room_repo,
    get_reservation_repo,
    require_permission,
    verify_api_key,
)
from otelms.api.mappers import guest_name as _guest_name
from otelms.api.mappers import room_response
from otelms.api.schemas import (
    HousekeepingItem,
    HousekeepingResetResponse,
    HousekeepingResponse,
    HousekeepingStatusResponse,
    HousekeepingStatusUpdate,
)
from otelms.config.settings import settings
from otelms.domain.entities import Reservation, RoomAvailability
from otelms.utils.timezone import ensure_utc, to_ecuador, utc_now
from otelms.domain.repositories import (
    HousekeepingStatusRepository,
    ReservationRepository,
    RoomRepository,
)

router = APIRouter(
    prefix="/housekeeping",
    tags=["housekeeping"],
    dependencies=[Depends(verify_api_key)],
)

# Status labels for human-readable output
_STATUS_LABELS = {0: "pending", 1: "in_progress", 2: "cleaned"}


def _build_item(res, cleaning_type: str, target_date: date) -> HousekeepingItem:
    """Construye un HousekeepingItem a partir de una reserva."""
    room_data = room_response(res.room) if res.room else None
    entrada = res.check_in.date() if res.check_in else target_date
    salida = res.check_out.date() if res.check_out else target_date
    noches_restantes = max((salida - target_date).days, 0)

def _build_item(
    res: Reservation,
    cleaning_type: str,
    target_date: date,
    notes_map: dict[str, str] | None = None,
) -> HousekeepingItem:
    room_data = room_response(res.room) if res.room else None
    co_date = res.check_out.date() if res.check_out else target_date
    noches_restantes = max((co_date - target_date).days, 0)
    return HousekeepingItem(
        room_id=res.room_id,
        room_name=room_data.name if room_data else res.room_id,
        category_id=room_data.category_id if room_data else None,
        category_name=room_data.category.name if room_data and room_data.category else None,
        reservation_id=res.id,
        guest_name=_guest_name(res),
        check_in=res.check_in,
        check_out=res.check_out,
        adults=res.adults or 1,
        children=res.children or 0,
        nights_remaining=noches_restantes,
        cleaning_type=cleaning_type,
        status=res.status,
        last_cleaned_at=getattr(res.room, "last_cleaned_at", None) if res.room else None,
        notes=(notes_map or {}).get(res.room_id),
    )


async def _get_future_reservations(
    session: AsyncSession, hotel_id: str, target_date: date
) -> list:
    """Obtiene reservas futuras (check_in > target_date) para un hotel."""
    stmt = (
        select(Reservation)
        .where(
            Reservation.hotel_id == hotel_id,
            Reservation.status == 1,
            func.date(Reservation.check_in) > target_date,
        )
        .order_by(Reservation.check_in)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("", response_model=HousekeepingResponse)
async def get_housekeeping(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=lambda: to_ecuador(utc_now()).date(),
        description="Fecha a consultar (YYYY-MM-DD)",
    ),
    room_repo: RoomRepository = Depends(get_room_repo),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
    hk_repo: HousekeepingStatusRepository = Depends(get_housekeeping_status_repo),
    session: AsyncSession = Depends(get_db),
    _ = Depends(require_permission("housekeeping:read")),
) -> HousekeepingResponse:
    """Obtiene el plan de limpieza para una fecha.

    **Limpieza completa (full):** Habitaciones con check-out en la fecha consultada.
    El huésped ya se fue, la habitación está libre y necesita limpieza profunda.

    **Limpieza continua (continuous):** Habitaciones que pernoctan en la fecha consultada
    (check_in <= fecha < check_out). El huésped sigue dentro, limpieza ligera de mantenimiento.

    **Bloqueadas (blocked):** Habitaciones sin reserva activa para la fecha.

    **Ingresos (income_generating):** Habitaciones con reserva futura que generara ingresos.

    El día de salida NO cuenta como noche de pernocta: el huésped se va por la mañana.

    Las habitaciones ya marcadas como limpias (status=2) no aparecen en el listado.
    """
    # Obtener room_ids ya limpias y notas para esa fecha
    cleaned_room_ids = await hk_repo.get_cleaned_room_ids_for_date(hotel_id, target_date)
    notes_map = await hk_repo.get_notes_map_for_date(hotel_id, target_date)

    # Habitaciones bloqueadas por mantenimiento (candado) en room_availability
    day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    avail_stmt = select(RoomAvailability.room_id).where(
        RoomAvailability.hotel_id == hotel_id,
        RoomAvailability.room_id.isnot(None),
        RoomAvailability.is_blocked.is_(True),
        RoomAvailability.start_date < day_end,
        RoomAvailability.end_date >= day_start,
    )
    maint_blocked_ids = {row[0] for row in (await session.execute(avail_stmt)).all()}
    # 1. Check-outs de hoy = limpieza completa
    checkouts = await res_repo.get_checkouts_for_date(hotel_id, target_date)
    # Excluir habitaciones Overbooking (categoria 21) y ya limpias
    checkouts = [r for r in checkouts if r.room and r.room.category_id != "21" and r.room_id not in cleaned_room_ids]

    # 2. Ocupadas (pernoctan) = limpieza continua
    # Solo incluye reservas que YA estaban check-in antes de hoy (check_in < today).
    # Las que check-in hoy son ingresos futuros, no pernoctan.
    occupied = await room_repo.get_occupied_for_date(hotel_id, target_date)
    # Excluir reservas de habitaciones Overbooking (categoria 21) y ya limpias
    occupied = [r for r in occupied if r.room.category_id != "21" and r.room_id not in cleaned_room_ids]
    # Filtrar solo las que pernoctan de verdad (check_in < today)
    continuous_reservations = [r for r in occupied if r.check_in and r.check_in.date() < target_date]

    occupied_room_ids = {r.room_id for r in occupied}
    checkout_room_ids = {r.room_id for r in checkouts}
    continuous_room_ids = {r.room_id for r in continuous_reservations}

    # 3. Habitaciones con ingresos: check-ins de hoy (nuevos arrivals)
    # Solo incluye reservas que check-in hoy (check_in == today).
    checkin_today = [
        r for r in occupied
        if r.check_in and r.check_in.date() == target_date
        and r.room_id not in continuous_room_ids
    ]
    checkin_today_room_ids = {r.room_id for r in checkin_today}

    # 4. Habitaciones bloqueadas: sin reserva activa para la fecha
    # Una reserva futura (check_in > hoy) NO es activa para hoy, así que
    # la habitación sigue bloqueada. Solo se excluyen ocupadas, check-out hoy
    # y check-in de hoy (que ya van a income).
    # Excluir habitaciones de categoria "Overbooking" (id=21) de todos los calculos
    # y excluir las ya marcadas como limpias
    all_rooms = await room_repo.get_by_hotel_with_category(hotel_id)
    blocked_rooms_data = [
        r for r in all_rooms
        if r.id not in occupied_room_ids
        and r.id not in checkout_room_ids
        and r.id not in checkin_today_room_ids
        and r.id not in cleaned_room_ids
        and r.category_id != "21"
    ]

    full_cleaning: list[HousekeepingItem] = []
    continuous_cleaning: list[HousekeepingItem] = []
    dusting_rooms: list[HousekeepingItem] = []
    blocked_rooms: list[HousekeepingItem] = []
    income_generating: list[HousekeepingItem] = []

    # Anadir check-outs (limpieza completa)
    for res in checkouts:
        full_cleaning.append(_build_item(res, "full", target_date, notes_map))

    # Anadir ocupadas que pernoctan (limpieza continua)
    # Excluir habitaciones que tienen check-out hoy (ya son full_cleaning)
    for res in continuous_reservations:
        if res.room_id not in checkout_room_ids:
            continuous_cleaning.append(_build_item(res, "stay_over", target_date, notes_map))

    # Clasificar habitaciones sin reserva activa en dusting (desocupadas >= N dias) o blocked
    now_utc = utc_now()
    dusting_days = settings.housekeeping_dusting_days
    for room in blocked_rooms_data:
        room_data = room_response(room)
        last_cleaned = getattr(room, "last_cleaned_at", None)
        is_maint_blocked = room.id in maint_blocked_ids
        needs_dusting = (
            not is_maint_blocked
            and (
                last_cleaned is None
                or (now_utc - ensure_utc(last_cleaned)).days >= dusting_days
            )
        )
        item = HousekeepingItem(
            room_id=room.id,
            room_name=room_data.name,
            category_id=room_data.category_id,
            category_name=room_data.category.name if room_data and room_data.category else None,
            reservation_id="",
            guest_name=None,
            check_in=target_date,
            check_out=target_date,
            adults=0,
            children=0,
            nights_remaining=0,
            cleaning_type="dusting" if needs_dusting else "blocked",
            status=0,
            last_cleaned_at=last_cleaned,
            notes=notes_map.get(room.id),
        )
        if needs_dusting:
            dusting_rooms.append(item)
        else:
            blocked_rooms.append(item)

    # Anadir ingresos (check-ins de hoy)
    for res in checkin_today:
        income_generating.append(_build_item(res, "income", target_date, notes_map))

    total_rooms_to_clean = (
        len(full_cleaning) + len(continuous_cleaning) + len(dusting_rooms) + len(income_generating)
    )

    return HousekeepingResponse(
        hotel_id=hotel_id,
        date=target_date,
        full_cleaning=full_cleaning,
        continuous_cleaning=continuous_cleaning,
        dusting_rooms=dusting_rooms,
        blocked_rooms=blocked_rooms,
        income_generating_rooms=income_generating,
        total_rooms_to_clean=total_rooms_to_clean,
    )


@router.patch(
    "/{room_id}",
    response_model=HousekeepingStatusResponse,
    dependencies=[Depends(require_permission("housekeeping:write"))],
)
async def update_housekeeping_status(
    hotel_id: str = Query(..., description="Hotel ID"),
    room_id: str = Path(..., description="Room ID"),
    target_date: date = Query(..., description="Fecha de la limpieza (YYYY-MM-DD)"),
    body: HousekeepingStatusUpdate = ...,
    hk_repo: HousekeepingStatusRepository = Depends(get_housekeeping_status_repo),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> HousekeepingStatusResponse:
    """Actualiza el estado de limpieza de una habitación para una fecha.

    Estados:
    - 0 = pending (pendiente)
    - 1 = in_progress (en proceso)
    - 2 = cleaned (limpia)

    Al marcar como limpia (status=2), la habitación no vuelve a aparecer en el
    listado de pendientes del GET /housekeeping para esa fecha.
    """
    # Validar que la habitación exista y pertenezca al hotel
    room = await room_repo.get_by_id(room_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found in hotel {hotel_id}",
        )
    if room.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found in hotel {hotel_id}",
        )

    # Validar status value
    if body.status not in (0, 1, 2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be 0 (pending), 1 (in_progress), or 2 (cleaned)",
        )

    result = await hk_repo.upsert(
        hotel_id=hotel_id,
        room_id=room_id,
        target_date=target_date,
        status=body.status,
        updated_by=body.updated_by,
        notes=body.notes,
    )
    if body.status == 2:
        room.last_cleaned_at = utc_now()
        await room_repo.session.flush()

    return HousekeepingStatusResponse(
        room_id=result.room_id,
        room_name=room.name,
        date=result.date,
        status=result.status,
        status_label=_STATUS_LABELS[result.status],
        notes=result.notes,
        updated_by=result.updated_by,
        updated_at=result.updated_at,
    )


@router.post(
    "/reset",
    response_model=HousekeepingResetResponse,
    dependencies=[Depends(require_permission("housekeeping:write"))],
)
async def reset_housekeeping(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(..., description="Fecha a reiniciar (YYYY-MM-DD)"),
    hk_repo: HousekeepingStatusRepository = Depends(get_housekeeping_status_repo),
) -> HousekeepingResetResponse:
    """Reinicia todos los estados de limpieza de una fecha a pending (0).

    Útil al cambiar de día: cuando llega una nueva fecha, todos los estados
    de limpieza del día anterior se reinician para empezar limpios.
    """
    count = await hk_repo.reset_date(hotel_id, target_date)
    return HousekeepingResetResponse(
        date=target_date,
        reset_count=count,
        message=f"Reseteados {count} estados de limpieza a pending",
    )