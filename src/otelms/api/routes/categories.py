"""
Category endpoints.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import (
    get_availability_repo,
    get_category_repo,
    get_room_repo,
    verify_api_key,
)
from otelms.api.mappers import category_response, room_response
from otelms.api.schemas import (
    CategoryAvailabilityResponse,
    CategoryAvailabilityRow,
    CategoryResponse,
    RoomResponse,
)
from otelms.domain.repositories import (
    CategoryAvailabilityRepository,
    CategoryRepository,
    RoomRepository,
)
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)

# El calendario de OtelMS cubre 46 días; es la ventana por defecto de la consulta.
DEFAULT_AVAILABILITY_DAYS = 45


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    hotel_id: str = Query(..., description="Hotel ID"),
    with_rooms: bool = Query(
        False, description="Deprecated: las habitaciones siempre se incluyen"
    ),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> list[CategoryResponse]:
    """Lista categorías de un hotel con sus habitaciones.

    Se mapea con category_response en vez de devolver la entidad: CategoryResponse
    y RoomResponse son recursivos entre sí y Pydantic aborta con `recursion_loop`
    si intenta seguir el ciclo category -> rooms -> room.category -> rooms.
    """
    categories = await cat_repo.get_with_rooms(hotel_id)
    return [category_response(c) for c in categories]


@router.get("/availability", response_model=CategoryAvailabilityResponse)
async def list_category_availability(
    hotel_id: str = Query(..., description="Hotel ID"),
    date_from: date = Query(
        default_factory=date.today, description="Primer día (YYYY-MM-DD)"
    ),
    date_to: date = Query(
        None, description="Último día (default: date_from + 45, la ventana del calendario)"
    ),
    category_id: str | None = Query(
        None, description="Filtra a una sola categoría"
    ),
    availability_repo: CategoryAvailabilityRepository = Depends(get_availability_repo),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> CategoryAvailabilityResponse:
    """Disponibilidad por categoría y día, tal como la publica OtelMS.

    El número sale de la fila de resumen del calendario (`div.calendar_sum`), no
    de restar las ocupadas al total: contrastado contra el portal, difieren 163
    de 414 celdas porque el hotel retiene habitaciones y bloquea días enteros.
    Se rellena con el último sync del calendario.
    """
    end = date_to or (date_from + timedelta(days=DEFAULT_AVAILABILITY_DAYS))
    if end < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to debe ser posterior o igual a date_from",
        )

    rows = await availability_repo.get_range(
        hotel_id, date_from, end, category_id=category_id
    )

    categories = await cat_repo.get_with_rooms(hotel_id)
    names = {c.id: c.name for c in categories}
    totals = {c.id: len(c.rooms) for c in categories}

    items = [
        CategoryAvailabilityRow(
            category_id=row.category_id,
            category_name=names.get(row.category_id),
            date=row.date,
            total_rooms=totals.get(row.category_id),
            available=row.available,
        )
        for row in rows
    ]

    return CategoryAvailabilityResponse(
        hotel_id=hotel_id,
        date_from=date_from,
        date_to=end,
        count=len(items),
        items=items,
    )


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> CategoryResponse:
    """Obtiene una categoría por ID."""
    categories = await cat_repo.get_with_rooms(hotel_id)
    for category in categories:
        if category.id == category_id:
            return category_response(category)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Category {category_id} not found",
    )


@router.get("/{category_id}/rooms", response_model=list[RoomResponse])
async def get_category_rooms(
    category_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> list[RoomResponse]:
    """Obtiene habitaciones de una categoría."""
    rooms = await room_repo.get_by_category(category_id)
    return [room_response(r) for r in rooms]
