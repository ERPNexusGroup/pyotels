"""
Category endpoints.
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
