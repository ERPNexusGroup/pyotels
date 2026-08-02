"""
Tasks package - Celery background tasks.
"""
from otelms.tasks.celery_app import celery_app
from otelms.tasks.scraping_tasks import (
    cleanup_old_sync_logs,
    health_check,
    sync_calendar,
    sync_categories,
    sync_full,
    sync_reservation_details,
)

__all__ = [
    "celery_app",
    "sync_calendar",
    "sync_categories",
    "sync_full",
    "sync_reservation_details",
    "health_check",
    "cleanup_old_sync_logs",
]
