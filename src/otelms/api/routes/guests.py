"""
Guest endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import get_db, verify_api_key, get_guest_repo
from otelms.api.schemas import GuestResponse, GuestBase
from otelms.domain.repositories import GuestRepository
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/guests", tags=["guests"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=List[GuestResponse])
async def list_guests(
    hotel_id: str = Query(..., description="Hotel ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, description="Search by name, email, document"),
    guest_repo: GuestRepository = Depends(get_guest_repo),
) -> List[GuestResponse]:
    """Lista huéspedes con búsqueda opcional."""
    if search:
        return await guest_repo.search(hotel_id, search, limit)
    return await guest_repo.get_by_hotel(hotel_id, limit, offset)


@router.get("/{guest_id}", response_model=GuestResponse)
async def get_guest(
    hotel_id: str = Query(..., description="Hotel ID"),
    guest_id: str = ...,
    guest_repo: GuestRepository = Depends(get_guest_repo),
) -> GuestResponse:
    """Obtiene un huésped por ID."""
    guest = await guest_repo.get_by_id(guest_id)
    if not guest or guest.hotel_id != hotel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guest {guest_id} not found",
        )
    return guest


@router.post("", response_model=GuestResponse, status_code=status.HTTP_201_CREATED)
async def create_guest(
    hotel_id: str = Query(..., description="Hotel ID"),
    guest_data: GuestBase = ...,
    guest_repo: GuestRepository = Depends(get_guest_repo),
) -> GuestResponse:
    """Crea un nuevo huésped."""
    guest_data.hotel_id = hotel_id
    guest = await guest_repo.create(**guest_data.model_dump())
    return guest