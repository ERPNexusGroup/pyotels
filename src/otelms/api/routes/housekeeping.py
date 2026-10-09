"""
Housekeeping endpoints - Limpieza de habitaciones.

Criterio:
- "limpieza completa" (full): habitaciones con check-out hoy (el huésped se fue, limpieza profunda)
- "limpieza continua" (stay_over): habitaciones que pernoctan esa noche (el huésped sigue, limpieza ligera)
"""
from datetime import date

from fastapi import APIRouter, Depends, Query

from otelms.api.dependencies import get_reservation_repo, get_room_repo, verify_api_key
from otelms.api.mappers import guest_name as _guest_name
from otelms.api.mappers import room_response
from otelms.api.schemas import HousekeepingResponse, HousekeepingItem
from otelms.domain.repositories import ReservationRepository, RoomRepository

router = APIRouter(prefix="/housekeeping", tags=["housekeeping"], dependencies=[Depends(verify_api_key)])


@router.get("", response_model=HousekeepingResponse)
async def get_housekeeping(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Fecha a consultar (YYYY-MM-DD)"
    ),
    room_repo: RoomRepository = Depends(get_room_repo),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> HousekeepingResponse:
    """Obtiene el plan de limpieza para una fecha.

    **Limpieza completa (full):** Habitaciones con check-out en la fecha consultada.
    El huésped ya se fue, la habitación está libre y necesita limpieza profunda.

    **Limpieza continua (stay_over):** Habitaciones que pernoctan en la fecha consultada
    (check_in <= fecha < check_out). El huésped sigue dentro, limpieza ligera de mantenimiento.

    El día de salida NO cuenta como noche de pernocta: el huésped se va por la mañana.
    """
    # 1. Check-outs de hoy = limpieza completa
    checkouts = await res_repo.get_checkouts_for_date(hotel_id, target_date)

    # 2. Ocupadas (pernoctan) = limpieza continua
    # Usamos get_occupied_for_date que ya trae room/categoría/guest precargados
    occupied = await room_repo.get_occupied_for_date(hotel_id, target_date)

    items: list[HousekeepingItem] = []

    # Añadir check-outs (limpieza completa)
    for res in checkouts:
        room_data = room_response(res.room) if res.room else None
        items.append(HousekeepingItem(
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
            nights_remaining=0,  # Ya no quedan noches, se van hoy
            cleaning_type="full",
            status=res.status,
        ))

    # Añadir ocupadas que pernoctan (limpieza continua)
    for res in occupied:
        # Calcular noches restantes desde target_date
        entrada = res.check_in.date() if res.check_in else target_date
        salida = res.check_out.date() if res.check_out else target_date
        noches_restantes = max((salida - target_date).days, 0)

        # Solo añadir si NO es check-out hoy (evitar duplicados)
        if res.check_out and res.check_out.date() == target_date:
            continue

        room_data = room_response(res.room) if res.room else None
        items.append(HousekeepingItem(
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
            cleaning_type="stay_over",
            status=res.status,
        ))

    full_count = sum(1 for i in items if i.cleaning_type == "full")
    stay_over_count = sum(1 for i in items if i.cleaning_type == "stay_over")

    return HousekeepingResponse(
        hotel_id=hotel_id,
        date=target_date,
        full_cleaning_count=full_count,
        stay_over_cleaning_count=stay_over_count,
        total_rooms_to_clean=full_count + stay_over_count,
        items=items,
    )


@router.get("/full-cleaning", response_model=list[HousekeepingItem])
async def get_full_cleaning(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Fecha a consultar (YYYY-MM-DD)"
    ),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> list[HousekeepingItem]:
    """Solo habitaciones con check-out hoy (limpieza completa / deep cleaning).

    Útil para el equipo de limpieza profunda: habitaciones que quedan libres.
    """
    checkouts = await res_repo.get_checkouts_for_date(hotel_id, target_date)

    items: list[HousekeepingItem] = []
    for res in checkouts:
        room_data = room_response(res.room) if res.room else None
        items.append(HousekeepingItem(
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
            nights_remaining=0,
            cleaning_type="full",
            status=res.status,
        ))
    return items


@router.get("/stay-over", response_model=list[HousekeepingItem])
async def get_stay_over_cleaning(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Fecha a consultar (YYYY-MM-DD)"
    ),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> list[HousekeepingItem]:
    """Solo habitaciones que pernoctan (limpieza continua / stay-over cleaning).

    Útil para el equipo de mantenimiento: habitaciones ocupadas que siguen con huésped.
    """
    occupied = await room_repo.get_occupied_for_date(hotel_id, target_date)

    items: list[HousekeepingItem] = []
    for res in occupied:
        # Excluir check-outs de hoy (ya están en full_cleaning)
        if res.check_out and res.check_out.date() == target_date:
            continue

        entrada = res.check_in.date() if res.check_in else target_date
        salida = res.check_out.date() if res.check_out else target_date
        noches_restantes = max((salida - target_date).days, 0)

        room_data = room_response(res.room) if res.room else None
        items.append(HousekeepingItem(
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
            cleaning_type="stay_over",
            status=res.status,
        ))
    return items