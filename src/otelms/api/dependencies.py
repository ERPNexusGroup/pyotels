"""
FastAPI dependencies - Inyección de dependencias.
"""
from typing import AsyncGenerator, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.config.settings import settings
from otelms.domain.repositories.database import get_db_session, db
from otelms.domain.repositories import (
    HotelRepository,
    CategoryRepository,
    RoomRepository,
    GuestRepository,
    ReservationRepository,
    ServiceRepository,
    PaymentRepository,
    SyncLogRepository,
    ApiKeyRepository,
)
from otelms.domain.entities import ApiKey
from otelms.utils.cache import cache, CacheManager
from otelms.scraping.orchestrator import ScrapingOrchestrator
from otelms.services.sync_service import SyncService
from otelms.scraping.rate_limiter import rate_limiter, RateLimiter
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# DATABASE
# ============================================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para sesión de base de datos."""
    # get_db_session() returns an async generator, use async for
    async for session in get_db_session():
        yield session


# ============================================================
# REPOSITORIES
# ============================================================
async def get_hotel_repo(session: AsyncSession = Depends(get_db)) -> HotelRepository:
    return HotelRepository(session)


async def get_category_repo(session: AsyncSession = Depends(get_db)) -> CategoryRepository:
    return CategoryRepository(session)


async def get_room_repo(session: AsyncSession = Depends(get_db)) -> RoomRepository:
    return RoomRepository(session)


async def get_guest_repo(session: AsyncSession = Depends(get_db)) -> GuestRepository:
    return GuestRepository(session)


async def get_reservation_repo(session: AsyncSession = Depends(get_db)) -> ReservationRepository:
    return ReservationRepository(session)


async def get_service_repo(session: AsyncSession = Depends(get_db)) -> ServiceRepository:
    return ServiceRepository(session)


async def get_payment_repo(session: AsyncSession = Depends(get_db)) -> PaymentRepository:
    return PaymentRepository(session)


async def get_sync_log_repo(session: AsyncSession = Depends(get_db)) -> SyncLogRepository:
    return SyncLogRepository(session)


async def get_api_key_repo(session: AsyncSession = Depends(get_db)) -> ApiKeyRepository:
    return ApiKeyRepository(session)


# ============================================================
# CACHE
# ============================================================
async def get_cache() -> CacheManager:
    """Dependency para cache manager."""
    if not cache._backend:
        await cache.initialize()
    return cache


# ============================================================
# SCRAPING / SYNC SERVICES
# ============================================================
_scraping_orchestrator: Optional[ScrapingOrchestrator] = None
_sync_service: Optional[SyncService] = None


async def get_scraping_orchestrator() -> ScrapingOrchestrator:
    """Dependency para orquestador de scraping (singleton por request)."""
    global _scraping_orchestrator
    if _scraping_orchestrator is None:
        _scraping_orchestrator = ScrapingOrchestrator(
            hotel_id=settings.otelms_default_hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        await _scraping_orchestrator.initialize()
    return _scraping_orchestrator


async def get_sync_service() -> SyncService:
    """Dependency para servicio de sincronización."""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService(
            hotel_id=settings.otelms_default_hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        await _sync_service.initialize()
    return _sync_service


# ============================================================
# AUTHENTICATION
# ============================================================
async def verify_api_key(
    api_key: str = Header(..., alias=settings.api_key_header),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> ApiKey:
    """Verifica API Key en header."""
    import hashlib

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Buscar en BD
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    result = await api_key_repo.session.execute(stmt)
    key_obj = result.scalar_one_or_none()

    if not key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Actualizar last_used_at
    from datetime import datetime, timezone
    key_obj.last_used_at = datetime.now(timezone.utc)
    await api_key_repo.session.flush()

    return key_obj


async def optional_api_key(
    api_key: Optional[str] = Header(None, alias=settings.api_key_header),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> Optional[ApiKey]:
    """API Key opcional (para endpoints públicos con rate limit opcional)."""
    if not api_key:
        return None

    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    result = await api_key_repo.session.execute(stmt)
    return result.scalar_one_or_none()


# ============================================================
# RATE LIMITING DEPENDENCY
# ============================================================
from otelms.scraping.rate_limiter import rate_limiter, RateLimiter


async def get_rate_limiter() -> RateLimiter:
    """Dependency para rate limiter."""
    return rate_limiter


async def rate_limit_dependency(
    api_key: Optional[ApiKey] = Depends(optional_api_key),
    rl: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Rate limiting basado en API key o IP."""
    # TODO: Implementar rate limiting por API key / IP
    pass