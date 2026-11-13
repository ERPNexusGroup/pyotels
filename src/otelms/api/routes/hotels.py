"""
Hotel management endpoints.
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status

from otelms.api.dependencies import (
    get_dealer_repo,
    get_hotel_repo,
    get_payment_method_repo,
    get_property_service_repo,
    verify_api_key,
)
from otelms.api.mappers import (
    dealer_response,
    payment_method_response,
    property_service_response,
)
from otelms.api.schemas import (
    DealerResponse,
    FrontDeskStatusResponse,
    HotelBase,
    HotelCreate,
    HotelResponse,
    PaymentMethodResponse,
    PriceCalendarCellResponse,
    PropertyServiceResponse,
)
from otelms.domain.repositories import (
    DealerRepository,
    HotelRepository,
    PaymentMethodRepository,
    PropertyServiceRepository,
)
from otelms.scraping.setup_extract import SetupExtractor
from otelms.services.setup_sync_service import SetupSyncService
from otelms.utils.crypto import credential_encryption
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/hotels", tags=["hotels"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=list[HotelResponse])
async def list_hotels(
    active_only: bool = True,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> list[HotelResponse]:
    """Lista todos los hoteles configurados."""
    if active_only:
        hotels = await hotel_repo.get_active()
    else:
        hotels = await hotel_repo.get_all(limit=100)
    return [HotelResponse.model_validate(h) for h in hotels]


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
    return HotelResponse.model_validate(hotel)


@router.post("", response_model=HotelResponse, status_code=status.HTTP_201_CREATED)
async def create_hotel(
    hotel_data: HotelCreate,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> HotelResponse:
    """Crea un nuevo hotel."""

    # Verificar si ya existe
    existing = await hotel_repo.get_by_id(hotel_data.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Hotel {hotel_data.id} already exists",
        )

    pwd_hash = hashlib.sha256(hotel_data.password.encode()).hexdigest()
    payload = hotel_data.model_dump(exclude={"password"})
    payload["password_hash"] = pwd_hash
    payload["encrypted_password"] = credential_encryption.encrypt(hotel_data.password)
    hotel = await hotel_repo.create(**payload)
    return HotelResponse.model_validate(hotel)


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
    return HotelResponse.model_validate(hotel)


@router.post("/{hotel_id}/rotate-password", response_model=dict)
async def rotate_hotel_password(
    hotel_id: str,
    new_password: str,
    hotel_repo: HotelRepository = Depends(get_hotel_repo),
) -> dict:
    """Rota la contraseña de un hotel (encripta y almacena)."""


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


@router.get("/{hotel_id}/dealers", response_model=list[DealerResponse])
async def list_dealers(
    hotel_id: str,
    active_only: bool = True,
    dealer_repo: DealerRepository = Depends(get_dealer_repo),
) -> list[DealerResponse]:
    """Lista canales de venta / dealers de OtelMS."""
    dealers = await dealer_repo.get_by_hotel(hotel_id, active_only=active_only)
    return [dealer_response(d) for d in dealers]


@router.get("/{hotel_id}/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    hotel_id: str,
    active_only: bool = True,
    pm_repo: PaymentMethodRepository = Depends(get_payment_method_repo),
) -> list[PaymentMethodResponse]:
    """Lista métodos de pago configurados en OtelMS."""
    pms = await pm_repo.get_by_hotel(hotel_id, active_only=active_only)
    return [payment_method_response(p) for p in pms]


@router.get("/{hotel_id}/services", response_model=list[PropertyServiceResponse])
async def list_property_services(
    hotel_id: str,
    active_only: bool = True,
    svc_repo: PropertyServiceRepository = Depends(get_property_service_repo),
) -> list[PropertyServiceResponse]:
    """Lista servicios y descripciones del hotel."""
    services = await svc_repo.get_by_hotel(hotel_id, active_only=active_only)
    return [property_service_response(s) for s in services]


@router.post("/{hotel_id}/sync-setup", response_model=dict)
async def sync_hotel_setup(hotel_id: str) -> dict:
    """Sincroniza en vivo los datos maestros desde OtelMS."""
    sync_svc = SetupSyncService(hotel_id)
    return await sync_svc.sync_all()


@router.get("/{hotel_id}/status", response_model=FrontDeskStatusResponse)
async def get_frontdesk_status(hotel_id: str) -> FrontDeskStatusResponse:
    """Obtiene el estado en vivo de Front Desk desde /reservation_c2/status."""
    async with SetupExtractor(hotel_id=hotel_id) as extractor:
        status_data = await extractor.fetch_status()
    return FrontDeskStatusResponse(
        hotel_id=hotel_id,
        status_date=status_data.get("status_date", ""),
        departures_today=status_data.get("departures_today", 0),
        arrivals_today=status_data.get("arrivals_today", 0),
        inhouse_today=status_data.get("inhouse_today", 0),
    )


@router.get("/{hotel_id}/price-calendar", response_model=list[PriceCalendarCellResponse])
async def get_price_calendar(
    hotel_id: str,
    dealer_id: str | None = None,
    category_id: str | None = None,
) -> list[PriceCalendarCellResponse]:
    """Consulta la matriz de precios por canal de venta desde /reservation_c2/price_calendar."""
    async with SetupExtractor(hotel_id=hotel_id) as extractor:
        cells = await extractor.fetch_price_calendar()

    results = []
    for c in cells:
        if dealer_id and c.get("dealer_id") != str(dealer_id):
            continue
        if category_id and c.get("category_id") != str(category_id):
            continue
        results.append(
            PriceCalendarCellResponse(
                date=c.get("date", ""),
                room_id=c.get("room_id", ""),
                dealer_id=c.get("dealer_id", ""),
                category_id=c.get("category_id", ""),
                price=c.get("price"),
            )
        )
    return results
