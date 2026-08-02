"""
Category endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import get_category_repo, get_room_repo, verify_api_key
from otelms.api.schemas import CategoryResponse
from otelms.domain.repositories import CategoryRepository
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    hotel_id: str = Query(..., description="Hotel ID"),
    with_rooms: bool = Query(False, description="Include rooms"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> list[CategoryResponse]:
    """Lista categorías de un hotel."""
    if with_rooms:
        return await cat_repo.get_with_rooms(hotel_id)
    return await cat_repo.get_by_hotel(hotel_id)


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    hotel_id: str = Query(..., description="Hotel ID"),
    category_id: str = ...,
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> CategoryResponse:
    """Obtiene una categoría por ID."""
    category = await cat_repo.get_by_id(category_id)
    if not category or category.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )
    return category


@router.get("/{category_id}/rooms", response_model=list[dict])
async def get_category_rooms(
    hotel_id: str = Query(..., description="Hotel ID"),
    category_id: str = ...,
    room_repo = Depends(get_room_repo),
) -> list[dict]:
    """Obtiene habitaciones de una categoría."""
    return await room_repo.get_by_category(category_id)
