"""
Category endpoints - solo lectura desde la base de datos.

Tres endpoints informativos que devuelven lo que el scraping/sync ya dejó
persistido. No calculan disponibilidad ni tarifas: eso es responsabilidad
de /rooms y /restrictions.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import get_category_repo, get_room_repo, verify_api_key
from otelms.api.mappers import category_response, room_response
from otelms.api.schemas import CategoryResponse, RoomResponse
from otelms.domain.repositories import CategoryRepository, RoomRepository
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    hotel_id: str = Query(..., description="Hotel ID"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> list[CategoryResponse]:
    """Todas las categorías del hotel con sus habitaciones.

    Se mapea con category_response en vez de devolver la entidad: CategoryResponse
    y RoomResponse son recursivos entre sí y Pydantic aborta con `recursion_loop`
    si intenta seguir el ciclo category -> rooms -> room.category -> rooms.
    """
    categories = await cat_repo.get_with_rooms(hotel_id)
    return [category_response(c) for c in categories]


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> CategoryResponse:
    """Información detallada de una categoría, incluidas sus habitaciones."""
    category = await cat_repo.get_by_id_with_rooms(hotel_id, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )
    return category_response(category)


@router.get("/{category_id}/rooms", response_model=list[RoomResponse])
async def get_category_rooms(
    category_id: str,
    hotel_id: str = Query(..., description="Hotel ID"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
    room_repo: RoomRepository = Depends(get_room_repo),
) -> list[RoomResponse]:
    """Habitaciones asignadas a una categoría."""
    category = await cat_repo.get_by_id_with_rooms(hotel_id, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )
    rooms = await room_repo.get_by_category(category_id)
    return [room_response(r) for r in rooms]
