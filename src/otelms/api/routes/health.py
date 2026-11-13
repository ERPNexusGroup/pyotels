"""
Health check endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import get_db
from otelms.api.schemas import HealthResponse
from otelms.config.settings import settings
from otelms.utils.cache import cache
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)


@router.get("", response_model=HealthResponse)
async def health_check(session: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Health check endpoint - verifica BD, caché, readiness y liveness."""

    checks = {}

    # Liveness - si llegamos hasta aquí el servicio está vivo
    checks["alive"] = True

    # Readiness - base de datos
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        checks["database"] = False

    # Readiness - caché Redis (si habilitado)
    if settings.cache_enabled:
        try:
            if cache._backend:
                await cache.get("_health_check")
                checks["cache"] = True
            else:
                checks["cache"] = False
        except Exception as e:
            logger.warning("Cache health check failed - Redis unavailable", error=str(e))
            checks["cache"] = False
    else:
        checks["cache"] = True  # Cache disabled = not a problem

    # Readiness general (servicio listo para atender tráfico)
    all_ready = all(checks.values())
    checks["ready"] = all_ready

    # Estado global: healthy si todo OK, degraded si algo falló (sigue 200)
    status = "healthy" if all_ready else "degraded"

    return HealthResponse(
        status=status,
        checks=checks,
    )
