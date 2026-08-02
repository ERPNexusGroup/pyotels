"""
OpenTelemetry instrumentation for distributed tracing.
"""
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Gauge, Histogram

from otelms.config.settings import settings
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

# Prometheus metrics (existing + enhanced)
http_requests_total = Counter(
    "otelms_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "otelms_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

scraping_operations_total = Counter(
    "otelms_scraping_operations_total",
    "Total scraping operations",
    ["operation", "hotel_id", "status"],
)

scraping_duration_seconds = Histogram(
    "otelms_scraping_duration_seconds",
    "Scraping operation duration in seconds",
    ["operation", "hotel_id"],
)

sync_records_processed = Counter(
    "otelms_sync_records_processed_total",
    "Total records processed during sync",
    ["operation", "hotel_id", "type"],  # label values: created, updated
)

active_browsers = Gauge(
    "otelms_active_browsers",
    "Number of active browser instances",
)

browser_pool_size = Gauge(
    "otelms_browser_pool_size",
    "Total browser pool size",
)

cache_operations_total = Counter(
    "otelms_cache_operations_total",
    "Total cache operations",
    ["operation", "backend", "status"],
)

celery_tasks_total = Counter(
    "otelms_celery_tasks_total",
    "Total Celery tasks executed",
    ["task_name", "status"],
)

celery_task_duration_seconds = Histogram(
    "otelms_celery_task_duration_seconds",
    "Celery task duration in seconds",
    ["task_name"],
)

database_connections_active = Gauge(
    "otelms_database_connections_active",
    "Active database connections",
)

sync_errors_total = Counter(
    "otelms_sync_errors_total",
    "Total sync errors",
    ["operation", "hotel_id", "error_type"],
)


# OpenTelemetry setup
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def init_telemetry() -> None:
    """Initialize OpenTelemetry tracing and metrics."""
    global _tracer_provider, _meter_provider

    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled via config")
        return

    # Resource attributes
    resource = Resource.create({
        SERVICE_NAME: settings.otel_service_name,
        SERVICE_VERSION: "1.0.0",
        "environment": settings.app_env,
    })

    # Tracer provider
    _tracer_provider = TracerProvider(resource=resource)

    # Add span processors
    if settings.app_debug:
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter())
        )

    # If OTLP endpoint configured, add OTLP exporter
    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415  # dep opcional, no instalada por defecto
                OTLPSpanExporter,
            )
            otlp_exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                headers=settings.otel_exporter_otlp_headers,
            )
            _tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except ImportError:
            logger.warning("OTLP exporter not installed, skipping")

    trace.set_tracer_provider(_tracer_provider)

    # Meter provider for metrics
    readers = [
        PrometheusMetricReader(),
    ]
    _meter_provider = MeterProvider(resource=resource, metric_readers=readers)

    logger.info("OpenTelemetry initialized", service=settings.otel_service_name)


def get_tracer(name: str = "otelms"):
    """Get a tracer instance."""
    return trace.get_tracer(name)


@contextmanager
def trace_operation(operation_name: str, **attributes):
    """Context manager for tracing an operation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(operation_name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise


def record_scraping_metric(operation: str, hotel_id: str, status: str, duration: float, records_created: int = 0, records_updated: int = 0):
    """Record scraping operation metrics."""
    scraping_operations_total.labels(operation=operation, hotel_id=hotel_id, status=status).inc()
    scraping_duration_seconds.labels(operation=operation, hotel_id=hotel_id).observe(duration)
    if records_created:
        sync_records_processed.labels(operation=operation, hotel_id=hotel_id, type="created").inc(records_created)
    if records_updated:
        sync_records_processed.labels(operation=operation, hotel_id=hotel_id, type="updated").inc(records_updated)


def record_celery_metric(task_name: str, status: str, duration: float):
    """Record Celery task metrics."""
    celery_tasks_total.labels(task_name=task_name, status=status).inc()
    celery_task_duration_seconds.labels(task_name=task_name).observe(duration)


def record_cache_metric(operation: str, backend: str, status: str):
    """Record cache operation metrics."""
    cache_operations_total.labels(operation=operation, backend=backend, status=status).inc()


def record_sync_error(operation: str, hotel_id: str, error_type: str):
    """Record sync error metrics."""
    sync_errors_total.labels(operation=operation, hotel_id=hotel_id, error_type=error_type).inc()


def shutdown_telemetry() -> None:
    """Shutdown telemetry providers."""
    global _tracer_provider, _meter_provider

    if _tracer_provider:
        _tracer_provider.shutdown()
    if _meter_provider:
        _meter_provider.shutdown()

    logger.info("OpenTelemetry shutdown complete")
