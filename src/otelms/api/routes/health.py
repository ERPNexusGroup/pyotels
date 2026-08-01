"""
Health check endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.dependencies import get_db
from otelms.api.schemas import HealthResponse
from otelms.config.settings import settings
from otelms.utils.logging import get_logger

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)


@router.get("", response_model=HealthResponse)
async def health_check(session: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Health check endpoint - verifica BD y servicios."""
    checks = {}

    # Check database
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        checks["database"] = False

    # Check Redis (if enabled) - don't fail if Redis unavailable
    if settings.cache_enabled:
        try:
            from otelms.utils.cache import cache
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

    # Overall status - degraded if any check fails, but still return 200
    all_healthy = all(checks.values())
    status = "healthy" if all_healthy else "degraded"

    return HealthResponse(
        status=status,
        checks=checks,
    )


@router.get("/ready")
async def readiness_check() -> dict:
    """Readiness check para Kubernetes."""
    return {"ready": True, "service": "otelms-api"}


@router.get("/live")
async def liveness_check() -> dict:
    """Liveness check para Kubernetes."""
    return {"alive": True, "service": "otelms-api"}