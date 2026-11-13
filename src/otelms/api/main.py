"""
Main FastAPI application factory.
"""
import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import REGISTRY, Counter, Histogram, generate_latest
from starlette.responses import Response

from otelms.api.routes import (
    admin,
    categories,
    guests,
    health,
    hotels,
    housekeeping,
    reservations,
    restrictions,
    rooms,
    websockets,
)
from otelms.config.settings import settings
from otelms.domain.repositories.database import close_db, init_db
from otelms.scraping.browser import browser_pool
from otelms.utils.cache import cache
from otelms.utils.logging import get_logger, setup_logging
from otelms.utils.telemetry import init_telemetry, shutdown_telemetry
from otelms.scraping.rate_limiter import rate_limiter

logger = get_logger(__name__)


# Prometheus metrics
def create_metrics() -> tuple[Counter | None, Histogram | None]:
    """Create Prometheus metrics, handling duplicate registration."""

    # Check if metrics already exist
    existing_names = set()
    for collector in REGISTRY._collector_to_names:
        for name in REGISTRY._collector_to_names[collector]:
            existing_names.add(name)

    metrics: dict[str, Any] = {}

    if "otelms_http_requests_total" not in existing_names:
        metrics["request_count"] = Counter(
            "otelms_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status"],
        )
    else:
        # Get existing metric
        for collector in REGISTRY._collector_to_names:
            if "otelms_http_requests_total" in REGISTRY._collector_to_names[collector]:
                metrics["request_count"] = collector
                break

    if "otelms_http_request_duration_seconds" not in existing_names:
        metrics["request_latency"] = Histogram(
            "otelms_http_request_duration_seconds",
            "HTTP request latency",
            ["method", "endpoint"],
        )
    else:
        for collector in REGISTRY._collector_to_names:
            if "otelms_http_request_duration_seconds" in REGISTRY._collector_to_names[collector]:
                metrics["request_latency"] = collector
                break

    return metrics.get("request_count"), metrics.get("request_latency")


_count_raw, _latency_raw = create_metrics()
# create_metrics siempre rellena ambas claves (nuevo registro o recuperación);
# los asserts convierten el None teórico en un fallo rápido en lugar de un
# AttributeError en la primera request.
assert _count_raw is not None
assert _latency_raw is not None
REQUEST_COUNT: Counter = _count_raw
REQUEST_LATENCY: Histogram = _latency_raw


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - startup and shutdown."""
    # Set Windows Proactor event loop policy for subprocess support (Camoufox/Playwright)
    # Must be set before any asyncio operations that might create subprocesses
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # Startup
    logger.info("Starting OtelMS API", version="1.0.0", env=settings.app_env)

    # Setup logging
    setup_logging()

    # Initialize telemetry
    init_telemetry()

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize cache
    await cache.initialize()
    logger.info("Cache initialized")

    # Initialize browser pool (non-blocking - if it fails, log and continue)
    try:
        await browser_pool.initialize()
        logger.info("Browser pool initialized")
    except NotImplementedError as e:
        logger.warning("Browser pool initialization failed - scraping features unavailable", error=str(e))
        logger.warning("Run with proper event loop policy or on Linux for full scraping support")
    except Exception as e:
        logger.error("Browser pool initialization failed", error=str(e))

    yield

    # Shutdown
    logger.info("Shutting down OtelMS API")

    await browser_pool.close()
    logger.info("Browser pool closed")

    await cache.close()
    logger.info("Cache closed")

    await close_db()
    logger.info("Database connections closed")

    shutdown_telemetry()
    logger.info("Telemetry shutdown complete")


def create_app() -> FastAPI:
    """Factory function to create FastAPI app."""
    app = FastAPI(
        title="OtelMS API",
        description="Unofficial API for OtelMS - Scraping and data access for hotel reservations",
        version="1.0.0",
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
        openapi_url="/openapi.json" if settings.app_debug else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_debug else ["https://yourdomain.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting middleware (fast fallback when Redis unavailable)
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: Any) -> Any:
        """Apply rate limiting based on API key or IP."""
        # Determine rate limit key: API key if present, otherwise IP
        api_key = request.headers.get(settings.api_key_header)
        if api_key:
            key = f"apikey:{api_key}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = f"ip:{client_ip}"

        try:
            await rate_limiter.wait_if_needed(key, 1)
        except Exception as e:
            # If rate limiter fails (e.g., Redis down mid-flight), log and allow request
            # to avoid blocking all traffic on rate limiter issues
            logger.warning("Rate limiter error, allowing request", key=key, error=str(e))

        response = await call_next(request)
        return response

    # Middleware for metrics
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Any) -> Any:
        start = time.time()

        response = await call_next(request)

        duration = time.time() - start
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)

        return response

    # Metrics endpoint (internal)
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        if not settings.api_enable_internal_sync:
            return JSONResponse(
                status_code=503,
                content={"detail": "Endpoint disabled in current API stage"},
            )
        return Response(generate_latest(), media_type="text/plain")

    # API Gateway middleware (feature flags por etapa)
    @app.middleware("http")
    async def api_gateway_middleware(request: Request, call_next: Any) -> Any:
        path = request.url.path
        method = request.method.upper()

        # Root siempre disponible (info mínima)
        if path == "/":
            return await call_next(request)

        # /health y /metrics dependen de flag interno
        if path in {"/health", "/metrics"}:
            if not settings.api_enable_internal_sync:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        # WebSocket interno
        if path.startswith("/ws/"):
            if not settings.api_enable_internal_sync:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        # Admin (panel + CRUD/tareas admin)
        if path.startswith("/admin"):
            if not settings.api_enable_admin_routes:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        # Rutas legacy/redundantes específicas
        legacy_paths = {
            "/rooms/available",
            "/reservations/sync/all",
        }
        if path in legacy_paths:
            if not settings.api_enable_legacy_routes:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            # si legacy está habilitado, puede requerir además flags de lectura/escritura según método

        # Endpoints internos de sync (triggers e históricos operativos)
        sync_internal_paths = {
            "/hotels/{hotel_id}/sync-setup",  # path template not directly comparable; handle by prefix/pattern below
        }
        is_sync_internal = (
            (path.startswith("/reservations/sync") and path != "/reservations/sync/history")
            or path == "/reservations/sync/history"
            or (path.startswith("/reservations/") and path.endswith("/sync-deep"))
            or (path.startswith("/hotels/") and path.endswith("/sync-setup"))
        )
        if is_sync_internal:
            if not settings.api_enable_internal_sync:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        # Escrituras operativas (Fase 2)
        is_write_action = (
            (path.startswith("/housekeeping") and method in {"PATCH", "POST", "PUT", "DELETE"})
            or (path.startswith("/guests") and method in {"POST", "PUT", "PATCH", "DELETE"})
            or (path.startswith("/hotels") and method in {"POST", "PATCH", "PUT", "DELETE"} and not path.endswith("/sync-setup"))
            or (path.startswith("/reservations") and method in {"POST", "PATCH", "PUT", "DELETE"} and not is_sync_internal)
        )
        # Nota: POST /hotels crea hotel y POST /hotels/{id}/rotate-password son mutaciones; se tratan como F2 write/admin-like por etapa.
        # Para simplificar Fase 1: cualquier mutación fuera de sync interno requiere API_ENABLE_WRITE_ACTIONS.
        if method in {"POST", "PATCH", "PUT", "DELETE"} and not is_sync_internal and not path.startswith("/admin"):
            if not settings.api_enable_write_actions:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        # Lectura pública (GET/HEAD/OPTIONS)
        if method in {"GET", "HEAD", "OPTIONS"}:
            if not settings.api_enable_read_public:
                return JSONResponse(status_code=503, content={"detail": "Endpoint disabled in current API stage"})
            return await call_next(request)

        return await call_next(request)

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Include routers (montaje condicional por feature flags de etapa)
    if settings.api_enable_internal_sync or settings.api_enable_read_public:
        # health router expone /health (lectura/estado) pero en etapa 1 se permite con internal/read flags según gateway
        app.include_router(health.router)
    if settings.api_enable_read_public or settings.api_enable_internal_sync or settings.api_enable_write_actions:
        app.include_router(hotels.router)
    if settings.api_enable_read_public or settings.api_enable_internal_sync or settings.api_enable_write_actions:
        app.include_router(reservations.router)
    if settings.api_enable_read_public or settings.api_enable_write_actions:
        app.include_router(guests.router)
    if settings.api_enable_read_public:
        app.include_router(categories.router)
    if settings.api_enable_read_public or settings.api_enable_legacy_routes:
        app.include_router(rooms.router)
    if settings.api_enable_read_public:
        app.include_router(restrictions.router)
    if settings.api_enable_read_public or settings.api_enable_write_actions:
        app.include_router(housekeeping.router)
    if settings.api_enable_internal_sync:
        app.include_router(websockets.router)
    if settings.api_enable_admin_routes:
        app.include_router(admin.router)

    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "OtelMS API",
            "version": "1.0.0",
            "description": "Unofficial API for OtelMS",
            "docs": "/docs" if settings.app_debug else "disabled in production",
        }

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "otelms.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        workers=settings.app_workers,
        reload=settings.app_debug,
        log_level=settings.log_level.lower(),
    )
