"""
Reservation endpoints.
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from otelms.api.dependencies import (
    get_reservation_repo,
    get_room_repo,
    get_sync_service,
    require_permission,
    verify_api_key,
)
from otelms.api.mappers import guest_name as _guest_name
from otelms.api.mappers import reservation_response, room_response
from otelms.api.schemas import (
    InHouseItem,
    InHouseResponse,
    PendingChargesItem,
    PendingChargesResponse,
    PaginationParams,
    ReservationFilterParams,
    ReservationListResponse,
    ReservationResponse,
    format_money,
)
from otelms.config.settings import settings
from otelms.domain.repositories import ReservationRepository, RoomRepository
from otelms.scraping.checkin import (
    check_in as otelms_check_in,
    check_out as otelms_check_out,
    move_reservation as otelms_move_reservation,
)
from otelms.services.sync_service import SyncService
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/reservations", tags=["reservations"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=ReservationListResponse)
async def list_reservations(
    hotel_id: str = Query(..., description="Hotel ID"),
    note_keyword: str | None = Query(None, description="Filtrar por palabra clave en notas"),
    money_unit: Literal["decimal", "cents"] | None = Query(
        None, description="Formato monetario de salida (decimal o cents)"
    ),
    pagination: PaginationParams = Depends(),
    filters: ReservationFilterParams = Depends(),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> ReservationListResponse:
    """Lista reservas con paginación y filtros.

    Las relaciones anidadas (huésped, habitación con su categoría, servicios y
    cobros) se mapean a mano: ReservationResponse se serializa con
    from_attributes y leerlas en diferido fuera del contexto async lanzaría
    MissingGreenlet.
    """
    unit = money_unit or settings.billing_money_unit
    rows = await res_repo.get_by_hotel(
        hotel_id=hotel_id,
        status=filters.status,
        check_in_from=filters.check_in_from,
        check_in_to=filters.check_in_to,
        check_out_from=filters.check_out_from,
        check_out_to=filters.check_out_to,
        note_keyword=note_keyword,
        limit=pagination.page_size,
        offset=(pagination.page - 1) * pagination.page_size,
    )
    items = [reservation_response(r, money_unit=unit) for r in rows]

    total = await res_repo.count_by_hotel(hotel_id, filters.status, note_keyword=note_keyword)

    return ReservationListResponse(
        items=items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=(total + pagination.page_size - 1) // pagination.page_size,
    )


@router.get("/in-house", response_model=InHouseResponse)
async def get_in_house(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: date = Query(
        default_factory=date.today, description="Noche a consultar (YYYY-MM-DD)"
    ),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> InHouseResponse:
    """Huéspedes dentro del hotel la noche de una fecha.

    **OtelMS no tiene endpoint de in-house.** Se comprobó el menú entero
    (`tests/manual/test_inhouse_discover.py`): no existe tal vista, así que el
    listado se deriva de las reservas que pernoctan esa fecha.

    El criterio es el rango de fechas, **no** `status == 2` ("Check in").
    Contrastado contra el portal: de 270 reservas, las 22 marcadas "Check in"
    tienen la salida ya pasada (entre 2026-08-08 y 2026-10-03) y ninguna
    pernocta el día consultado. Filtrar por estado daría 22 huéspedes que ya se
    fueron.

    El día de salida no cuenta: el huésped se va esa mañana.
    """
    reservations = await room_repo.get_occupied_for_date(hotel_id, target_date)

    items: list[InHouseItem] = []
    for res in reservations:
        # check_in/check_out son timestamps; las noches son días completos entre
        # ambos. El día de salida no es una noche.
        entrada = res.check_in.date() if res.check_in else target_date
        salida = res.check_out.date() if res.check_out else target_date
        noches = max((salida - entrada).days, 0)
        cumplidas = max((target_date - entrada).days, 0)

        items.append(InHouseItem(
            reservation_id=res.id,
            guest_name=_guest_name(res),
            room=room_response(res.room),
            check_in=res.check_in,
            check_out=res.check_out,
            nights=noches,
            nights_elapsed=min(cumplidas, noches),
            nights_remaining=max(noches - cumplidas, 0),
            adults=res.adults or 1,
            children=res.children or 0,
            total_price=res.total_price,
            status=res.status,
            source=res.source,
        ))

    return InHouseResponse(
        hotel_id=hotel_id,
        date=target_date,
        in_house_count=len(items),
        occupied_rooms=len({r.room_id for r in reservations if r.room_id}),
        items=items,
    )


@router.get("/pending-charges", response_model=PendingChargesResponse)
async def get_pending_charges(
    hotel_id: str = Query(..., description="Hotel ID"),
    only_pending: bool = Query(True, description="Solo reservas con saldo != 0"),
    money_unit: Literal["decimal", "cents"] | None = Query(
        None, description="Formato monetario de salida (decimal o cents)"
    ),
    limit: int = Query(100, ge=1, le=500, description="Máximo resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> PendingChargesResponse:
    """Saldo pendiente por reserva.

    Calcula `sum(services.total) - sum(payments.amount)` para cada reserva
    del hotel. Las reservas con saldo 0 (ya pagadas) se omiten salvo
    `only_pending=false`.

    Los servicios incluyen room_charges, room_price y cargos del folio,
    que el sync persiste como Services con `total` != 0.
    """
    unit = money_unit or settings.billing_money_unit
    raw_items = await res_repo.get_pending_charges(
        hotel_id=hotel_id,
        only_pending=only_pending,
        limit=limit,
        offset=offset,
    )

    total_pending_dec = sum(
        (Decimal(str(item["pending"])) for item in raw_items), Decimal("0.00")
    )
    formatted_items = [
        PendingChargesItem(
            **{
                **item,
                "money_unit": unit,
                "total_charges": format_money(Decimal(str(item["total_charges"])), unit),
                "total_paid": format_money(Decimal(str(item["total_paid"])), unit),
                "pending": format_money(Decimal(str(item["pending"])), unit),
            }
        )
        for item in raw_items
    ]

    return PendingChargesResponse(
        hotel_id=hotel_id,
        count=len(formatted_items),
        money_unit=unit,
        total_pending=format_money(total_pending_dec, unit),  # type: ignore[arg-type]
        items=formatted_items,
    )


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    reservation_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    money_unit: Literal["decimal", "cents"] | None = Query(
        None, description="Formato monetario de salida (decimal o cents)"
    ),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> ReservationResponse:
    """Obtiene una reserva con todos sus detalles."""
    unit = money_unit or settings.billing_money_unit
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    return reservation_response(reservation, money_unit=unit)


@router.post("/{reservation_id}/sync-deep", response_model=ReservationResponse)
async def sync_reservation_deep(
    reservation_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
    sync_service: SyncService = Depends(get_sync_service),
) -> ReservationResponse:
    """Fuerza la descarga profunda del folio y actualiza tarifas, vehículo, historial y notas."""
    await sync_service.sync_reservation_details(reservation_ids=[reservation_id])
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    return reservation_response(reservation)


class MoveReservationBody(BaseModel):
    """Payload para mover una reserva a otra habitación."""

    new_room_id: str


async def _resync_after_write(
    sync_service: SyncService,
    res_repo: ReservationRepository,
    hotel_id: str,
    reservation_id: str,
):
    try:
        await sync_service.sync_reservation_details(reservation_ids=[reservation_id])
    except Exception as exc:
        logger.warning(
            "Post-write re-sync failed, returning local state",
            reservation_id=reservation_id,
            error=str(exc),
        )
    return await res_repo.get_with_details(hotel_id, reservation_id)


@router.post(
    "/{reservation_id}/check-in",
    response_model=ReservationResponse,
    dependencies=[Depends(require_permission("reservations:write"))],
)
async def reservation_check_in(
    reservation_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
    sync_service: SyncService = Depends(get_sync_service),
) -> ReservationResponse:
    """Ejecuta check-in en OtelMS y re-sincroniza la reserva (Fase 2)."""
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    logger.info("Public check-in requested", hotel_id=hotel_id, reservation_id=reservation_id)
    ok = await otelms_check_in(hotel_id, reservation_id)
    if not ok:
        logger.error("Public check-in failed in OtelMS", hotel_id=hotel_id, reservation_id=reservation_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OtelMS check-in failed")
    reservation.status = 2
    await res_repo.session.commit()
    logger.info("Public check-in completed", hotel_id=hotel_id, reservation_id=reservation_id)
    refreshed = await _resync_after_write(sync_service, res_repo, hotel_id, reservation_id)
    return reservation_response(refreshed or reservation)


@router.post(
    "/{reservation_id}/check-out",
    response_model=ReservationResponse,
    dependencies=[Depends(require_permission("reservations:write"))],
)
async def reservation_check_out(
    reservation_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
    sync_service: SyncService = Depends(get_sync_service),
) -> ReservationResponse:
    """Ejecuta check-out en OtelMS y re-sincroniza la reserva (Fase 2)."""
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    logger.info("Public check-out requested", hotel_id=hotel_id, reservation_id=reservation_id)
    ok = await otelms_check_out(hotel_id, reservation_id)
    if not ok:
        logger.error("Public check-out failed in OtelMS", hotel_id=hotel_id, reservation_id=reservation_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OtelMS check-out failed")
    reservation.status = 4
    await res_repo.session.commit()
    logger.info("Public check-out completed", hotel_id=hotel_id, reservation_id=reservation_id)
    refreshed = await _resync_after_write(sync_service, res_repo, hotel_id, reservation_id)
    return reservation_response(refreshed or reservation)


@router.post(
    "/{reservation_id}/move",
    response_model=ReservationResponse,
    dependencies=[Depends(require_permission("reservations:write"))],
)
async def reservation_move_room(
    reservation_id: str,
    body: MoveReservationBody,
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
    room_repo: RoomRepository = Depends(get_room_repo),
    sync_service: SyncService = Depends(get_sync_service),
) -> ReservationResponse:
    """Mueve una reserva de habitación en OtelMS y re-sincroniza (Fase 2)."""
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    new_room = await room_repo.get_by_id(body.new_room_id)
    if not new_room or new_room.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target room {body.new_room_id} not found in hotel {hotel_id}",
        )
    logger.info(
        "Public move_reservation requested",
        hotel_id=hotel_id,
        reservation_id=reservation_id,
        old_room_id=reservation.room_id,
        new_room_id=body.new_room_id,
        category_id=new_room.category_id,
    )
    await otelms_move_reservation(
        hotel_id,
        reservation_id,
        room_id=body.new_room_id,
        category_id=new_room.category_id,
    )
    reservation.room_id = body.new_room_id
    await res_repo.session.commit()
    logger.info(
        "Public move_reservation completed",
        hotel_id=hotel_id,
        reservation_id=reservation_id,
        new_room_id=body.new_room_id,
    )
    refreshed = await _resync_after_write(sync_service, res_repo, hotel_id, reservation_id)
    return reservation_response(refreshed or reservation)


@router.get("/today/checkins", response_model=list[ReservationResponse])
async def get_today_checkins(
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> list[ReservationResponse]:
    """Obtiene check-ins programados para hoy."""
    rows = await res_repo.get_today_checkins(hotel_id)
    return [reservation_response(r) for r in rows]


@router.get("/today/checkouts", response_model=list[ReservationResponse])
async def get_today_checkouts(
    hotel_id: str = Query(..., description="Hotel ID"),
    money_unit: Literal["decimal", "cents"] | None = Query(
        None, description="Formato monetario de salida (decimal o cents)"
    ),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> list[ReservationResponse]:
    """Obtiene check-outs programados para hoy."""
    unit = money_unit or settings.billing_money_unit
    rows = await res_repo.get_today_checkouts(hotel_id)
    return [reservation_response(r, money_unit=unit) for r in rows]


@router.post("/sync/calendar", response_model=dict)
async def sync_calendar(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincroniza calendario desde OtelMS."""
    result = await sync_service.sync_calendar(target_date)
    return result.__dict__


@router.post("/sync/categories", response_model=dict)
async def sync_categories(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincroniza categorías desde OtelMS."""
    result = await sync_service.sync_categories(target_date)
    return result.__dict__


@router.post("/sync/full", response_model=dict)
async def full_sync(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincronización completa: calendario + categorías + detalles."""
    result = await sync_service.full_sync(target_date)
    return result.__dict__


@router.get("/sync/history", response_model=list[dict])
async def get_sync_history(
    hotel_id: str = Query(..., description="Hotel ID"),
    limit: int = Query(50, ge=1, le=200),
    sync_service: SyncService = Depends(get_sync_service),
) -> list[dict]:
    """Obtiene historial de sincronizaciones."""
    return await sync_service.get_sync_history(limit)


@router.post("/sync/all", response_model=dict)
async def sync_all_hotels(
    target_date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    max_concurrent: int = Query(3, ge=1, le=10, description="Max concurrent hotel syncs"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Trigger async sync for all active hotels."""
    result = await sync_service.sync_all_hotels(target_date=target_date, max_concurrent=max_concurrent)
    return result.__dict__


@router.post("/sync/{hotel_id}", response_model=dict)
async def sync_hotel(
    hotel_id: str,
    target_date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Trigger async sync for specific hotel."""
    result = await sync_service.full_sync(target_date)
    return result.__dict__
