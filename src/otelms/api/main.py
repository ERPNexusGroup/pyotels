"""
Main FastAPI application factory.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

from otelms.config.settings import settings
from otelms.utils.logging import setup_logging, get_logger
from otelms.utils.telemetry import init_telemetry, shutdown_telemetry
from otelms.domain.repositories.database import init_db, close_db
from otelms.utils.cache import cache
from otelms.scraping.browser import browser_pool
from otelms.api.routes import health, hotels, reservations, guests, categories, websockets

logger = get_logger(__name__)


# Prometheus metrics
def create_metrics():
    """Create Prometheus metrics, handling duplicate registration."""
    from prometheus_client import Counter, Histogram, REGISTRY
    from prometheus_client.metrics_core import Metric
    
    # Check if metrics already exist
    existing_names = set()
    for collector in REGISTRY._collector_to_names:
        for name in REGISTRY._collector_to_names[collector]:
            existing_names.add(name)
    
    metrics = {}
    
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


REQUEST_COUNT, REQUEST_LATENCY = create_metrics()


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

    # Middleware for metrics
    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        import time
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

    # Prometheus metrics endpoint
    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type="text/plain")

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
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

    # Include routers
    app.include_router(health.router)
    app.include_router(hotels.router)
    app.include_router(reservations.router)
    app.include_router(guests.router)
    app.include_router(categories.router)
    app.include_router(websockets.router)

    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root():
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