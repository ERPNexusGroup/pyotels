"""
Hotel management endpoints.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from otelms.api.dependencies import verify_api_key, get_hotel_repo
from otelms.api.schemas import HotelResponse, HotelCreate, HotelBase
from otelms.domain.repositories import HotelRepository
from otelms.domain.entities import Hotel
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/hotels", tags=["hotels"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=List[HotelResponse])
async def list_hotels(
    active_only: bool = True,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> List[HotelResponse]:
    """Lista todos los hoteles configurados."""
    if active_only:
        hotels = await hotel_repo.get_active()
    else:
        hotels = await hotel_repo.get_all(limit=100)
    return hotels


@router.get("/{hotel_id}", response_model=HotelResponse)
async def get_hotel(
    hotel_id: str,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> HotelResponse:
    """Obtiene un hotel por ID."""
    hotel = await hotel_repo.get_by_id(hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel {hotel_id} not found",
        )
    return hotel


@router.post("", response_model=HotelResponse, status_code=status.HTTP_201_CREATED)
async def create_hotel(
    hotel_data: HotelCreate,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> HotelResponse:
    """Crea un nuevo hotel."""
    import hashlib

    # Verificar si ya existe
    existing = await hotel_repo.get_by_id(hotel_data.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Hotel {hotel_data.id} already exists",
        )

    pwd_hash = hashlib.sha256(hotel_data.password.encode()).hexdigest()
    hotel = Hotel(
        id=hotel_data.id,
        name=hotel_data.name,
        domain=hotel_data.domain,
        username=hotel_data.username,
        password_hash=pwd_hash,
        is_active=True,
    )

    await hotel_repo.create(**hotel.__dict__)
    return hotel


@router.patch("/{hotel_id}", response_model=HotelResponse)
async def update_hotel(
    hotel_id: str,
    hotel_data: HotelBase,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> HotelResponse:
    """Actualiza un hotel."""
    hotel = await hotel_repo.get_by_id(hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel {hotel_id} not found",
        )

    update_data = hotel_data.model_dump(exclude_unset=True, exclude={"id"})
    for key, value in update_data.items():
        setattr(hotel, key, value)

    await hotel_repo.session.flush()
    await hotel_repo.session.refresh(hotel)
    return hotel


@router.delete("/{hotel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hotel(
    hotel_id: str,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> None:
    """Elimina un hotel (soft delete - marca inactivo)."""
    hotel = await hotel_repo.get_by_id(hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel {hotel_id} not found",
        )

    hotel.is_active = False
    await hotel_repo.session.flush()


@router.post("/{hotel_id}/rotate-password", response_model=dict)
async def rotate_hotel_password(
    hotel_id: str,
    new_password: str,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> dict:
    """Rota la contraseña de un hotel (encripta y almacena)."""
    import hashlib
    from otelms.utils.crypto import credential_encryption
    
    hotel = await hotel_repo.get_by_id(hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hotel {hotel_id} not found",
        )
    
    # Encrypt the new password
    encrypted_password = credential_encryption.encrypt(new_password)
    
    # Store both hash (for backwards compat) and encrypted password
    hotel.password_hash = hashlib.sha256(new_password.encode()).hexdigest()
    hotel.encrypted_password = encrypted_password
    
    await hotel_repo.session.flush()
    await hotel_repo.session.refresh(hotel)
    
    return {
        "message": "Password rotated successfully",
        "hotel_id": hotel_id,
    }