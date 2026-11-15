"""
FastAPI dependencies - Inyección de dependencias.
"""
import hashlib
import time
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.config.settings import settings
from otelms.domain.entities import ApiKey
from otelms.domain.repositories import (
    ApiKeyRepository,
    ApiKeyRoleRepository,
    CategoryAvailabilityRepository,
    CategoryRepository,
    ChannelRateRepository,
    DealerRepository,
    GuestRepository,
    HousekeepingStatusRepository,
    HotelRepository,
    PaymentMethodRepository,
    PaymentRepository,
    PropertyServiceRepository,
    ReservationChangeHistoryRepository,
    ReservationNightRateRepository,
    ReservationRepository,
    RoleRepository,
    RoomAvailabilityRepository,
    RoomRepository,
    ServiceRepository,
    SyncLogRepository,
)
from otelms.domain.repositories.database import get_db_session
from otelms.scraping.orchestrator import ScrapingOrchestrator
from otelms.scraping.rate_limiter import RateLimiter, rate_limiter
from otelms.services.sync_service import SyncService
from otelms.utils.cache import CacheManager, cache
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# DATABASE
# ============================================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para sesión de base de datos."""
    async with get_db_session() as session:
        yield session


# ============================================================
# REPOSITORIES
# ============================================================
async def get_hotel_repo(session: AsyncSession = Depends(get_db)) -> HotelRepository:
    return HotelRepository(session)


async def get_category_repo(session: AsyncSession = Depends(get_db)) -> CategoryRepository:
    return CategoryRepository(session)


async def get_category_availability_repo(
    session: AsyncSession = Depends(get_db),
) -> CategoryAvailabilityRepository:
    return CategoryAvailabilityRepository(session)


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


async def get_role_repo(session: AsyncSession = Depends(get_db)) -> RoleRepository:
    return RoleRepository(session)


async def get_api_key_role_repo(session: AsyncSession = Depends(get_db)) -> ApiKeyRoleRepository:
    return ApiKeyRoleRepository(session)


async def get_housekeeping_status_repo(
    session: AsyncSession = Depends(get_db),
) -> HousekeepingStatusRepository:
    return HousekeepingStatusRepository(session)


async def get_channel_rate_repo(
    session: AsyncSession = Depends(get_db),
) -> ChannelRateRepository:
    return ChannelRateRepository(session)


async def get_room_availability_repo(
    session: AsyncSession = Depends(get_db),
) -> RoomAvailabilityRepository:
    return RoomAvailabilityRepository(session)


async def get_dealer_repo(session: AsyncSession = Depends(get_db)) -> DealerRepository:
    return DealerRepository(session)


async def get_payment_method_repo(session: AsyncSession = Depends(get_db)) -> PaymentMethodRepository:
    return PaymentMethodRepository(session)


async def get_property_service_repo(session: AsyncSession = Depends(get_db)) -> PropertyServiceRepository:
    return PropertyServiceRepository(session)


async def get_night_rate_repo(session: AsyncSession = Depends(get_db)) -> ReservationNightRateRepository:
    return ReservationNightRateRepository(session)


async def get_history_repo(session: AsyncSession = Depends(get_db)) -> ReservationChangeHistoryRepository:
    return ReservationChangeHistoryRepository(session)


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
_scraping_orchestrator: ScrapingOrchestrator | None = None
_sync_service: SyncService | None = None


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
    api_key: str | None = Header(None, alias=settings.api_key_header),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> ApiKey:
    """Verifica API Key en header.

    Si `API_KEY_REQUIRED=false`, el endpoint se ejecuta sin clave (similar a
    `optional_api_key`). Esto permite probar localmente contra un contenedor
    que carga .env sin claves válidas, manteniendo la seguridad en producción.
    """
    if not settings.api_key_required:
        # API key verification bypassed (for local testing)
        # Create a dummy ApiKey object with safe defaults
        return ApiKey(
            id="local-test",
            name="Local Testing (API Key Disabled)",
            key_hash="",
            is_active=True,
            rate_limit=60,
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Buscar en BD usando metodo del repositorio (evita deteccion falsa de SQL injection)
    key_obj = await api_key_repo.get_by_key_hash(key_hash)

    if not key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Actualizar last_used_at
    await api_key_repo.update_last_used(key_obj.id)

    return key_obj


def require_permission(permission: str):
    """Dependency factory que verifica que el API Key autenticado tenga el permiso.

    Usa el sistema de roles: cada API Key puede tener múltiples roles, y cada rol
    tiene un conjunto de permisos (JSON array). Si la key no tiene el permiso
    solicitado, devuelve 403 Forbidden.

    En modo de desarrollo (API_KEY_REQUIRED=false) se omite la verificación.
    """

    async def _check_permission(
        api_key: ApiKey = Depends(verify_api_key),
        api_key_role_repo: ApiKeyRoleRepository = Depends(get_api_key_role_repo),
        role_repo: RoleRepository = Depends(get_role_repo),
    ) -> ApiKey:
        if not settings.api_key_required:
            return api_key

        roles = await api_key_role_repo.get_roles_for_key(api_key.id)
        for role in roles:
            perms = await role_repo.get_permissions(role.id)
            if permission in perms:
                return api_key

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission '{permission}' required",
        )

    return _check_permission


async def optional_api_key(
    api_key: str | None = Header(None, alias=settings.api_key_header),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> ApiKey | None:
    """API Key opcional (para endpoints públicos con rate limit opcional).

    Si `API_KEY_REQUIRED=false`, las request sin API key pasan igual
    (devuelve None). En producción (`API_KEY_REQUIRED=true`, default)
    el comportamiento es el mismo de siempre: sin key válida → 401.
    """
    if not api_key:
        if not settings.api_key_required:
            return None
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Usar metodo del repositorio para consistencia y evitar deteccion falsa
    return await api_key_repo.get_by_key_hash(key_hash)


# ============================================================
# RATE LIMITING DEPENDENCY
# ============================================================


async def get_rate_limiter() -> RateLimiter:
    """Dependency para rate limiter."""
    return rate_limiter


_live_rate_windows: dict[str, list[float]] = {}


def live_rate_limit(route_key: str):
    """Dependency que limita requests por minuto en endpoints en vivo (HTTP 429)."""

    async def _check() -> None:
        limit = settings.live_endpoint_rate_limit_per_minute
        if limit <= 0:
            return
        now = time.monotonic()
        cutoff = now - 60.0
        timestamps = [ts for ts in _live_rate_windows.get(route_key, []) if ts > cutoff]
        if len(timestamps) >= limit:
            retry_after = max(1, int(timestamps[0] + 60.0 - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded for live endpoint",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)
        _live_rate_windows[route_key] = timestamps

    return _check


async def rate_limit_dependency(
    api_key: ApiKey | None = Depends(optional_api_key),
    rl: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Rate limiting basado en API key o IP.

    TODO(#rate-limiting): Implementar rate limiting por API key / IP
    - Debe integrar con RateLimiter de rate_limiter.py
    - Claves: api_key.id si autenticado, IP si anónimo
    - Retornar 429 con Retry-After cuando exceda límite
    """
    pass