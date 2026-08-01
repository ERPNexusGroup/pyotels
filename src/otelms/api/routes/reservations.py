"""
Reservation endpoints.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import get_db, verify_api_key, get_reservation_repo, get_sync_service
from otelms.api.schemas import (
    ReservationResponse,
    ReservationListResponse,
    PaginationParams,
    ReservationFilterParams,
)
from otelms.domain.repositories import ReservationRepository
from otelms.services.sync_service import SyncService
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/reservations", tags=["reservations"], dependencies=[Depends(verify_api_key)])
logger = get_logger(__name__)


@router.get("", response_model=ReservationListResponse)
async def list_reservations(
    hotel_id: str = Query(..., description="Hotel ID"),
    pagination: PaginationParams = Depends(),
    filters: ReservationFilterParams = Depends(),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> ReservationListResponse:
    """Lista reservas con paginación y filtros."""
    items = await res_repo.get_by_hotel(
        hotel_id=hotel_id,
        status=filters.status,
        check_in_from=filters.check_in_from,
        check_in_to=filters.check_in_to,
        check_out_from=filters.check_out_from,
        check_out_to=filters.check_out_to,
        limit=pagination.page_size,
        offset=(pagination.page - 1) * pagination.page_size,
    )

    total = await res_repo.count_by_hotel(hotel_id, filters.status)

    return ReservationListResponse(
        items=items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=(total + pagination.page_size - 1) // pagination.page_size,
    )


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    hotel_id: str = Query(..., description="Hotel ID"),
    reservation_id: str = ...,
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> ReservationResponse:
    """Obtiene una reserva con todos sus detalles."""
    reservation = await res_repo.get_with_details(hotel_id, reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )
    return reservation


@router.get("/today/checkins", response_model=List[ReservationResponse])
async def get_today_checkins(
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> List[ReservationResponse]:
    """Obtiene check-ins programados para hoy."""
    return await res_repo.get_today_checkins(hotel_id)


@router.get("/today/checkouts", response_model=List[ReservationResponse])
async def get_today_checkouts(
    hotel_id: str = Query(..., description="Hotel ID"),
    res_repo: ReservationRepository = Depends(get_reservation_repo),
) -> List[ReservationResponse]:
    """Obtiene check-outs programados para hoy."""
    return await res_repo.get_today_checkouts(hotel_id)


@router.post("/sync/calendar", response_model=dict)
async def sync_calendar(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincroniza calendario desde OtelMS."""
    result = await sync_service.sync_calendar(target_date)
    return result.__dict__


@router.post("/sync/categories", response_model=dict)
async def sync_categories(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincroniza categorías desde OtelMS."""
    result = await sync_service.sync_categories(target_date)
    return result.__dict__


@router.post("/sync/full", response_model=dict)
async def full_sync(
    hotel_id: str = Query(..., description="Hotel ID"),
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Sincronización completa: calendario + categorías + detalles."""
    result = await sync_service.full_sync(target_date)
    return result.__dict__


@router.get("/sync/history", response_model=List[dict])
async def get_sync_history(
    hotel_id: str = Query(..., description="Hotel ID"),
    limit: int = Query(50, ge=1, le=200),
    sync_service: SyncService = Depends(get_sync_service),
) -> List[dict]:
    """Obtiene historial de sincronizaciones."""
    return await sync_service.get_sync_history(limit)


@router.post("/sync/all", response_model=dict)
async def sync_all_hotels(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    max_concurrent: int = Query(3, ge=1, le=10, description="Max concurrent hotel syncs"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Trigger async sync for all active hotels."""
    result = await sync_service.sync_all_hotels(target_date=target_date, max_concurrent=max_concurrent)
    return result.__dict__


@router.post("/sync/{hotel_id}", response_model=dict)
async def sync_hotel(
    hotel_id: str,
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    sync_service: SyncService = Depends(get_sync_service),
) -> dict:
    """Trigger async sync for specific hotel."""
    result = await sync_service.full_sync(target_date)
    return result.__dict__