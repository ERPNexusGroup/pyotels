"""
Celery tasks for scraping operations.
"""
import asyncio
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger

from otelms.config.settings import settings
from otelms.services.sync_service import SyncService

logger = get_task_logger(__name__)


def run_async(coro):
    """Helper to run async function in Celery task."""
    return asyncio.run(coro)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def sync_calendar(self, hotel_id: str, target_date: Optional[str] = None):
    """
    Sync calendar from OtelMS.
    Runs every 15 minutes via Celery Beat.
    """
    logger.info("Starting calendar sync task", hotel_id=hotel_id, target_date=target_date)
    
    try:
        sync_service = SyncService(
            hotel_id=hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        
        async def _run():
            await sync_service.initialize()
            try:
                result = await sync_service.sync_calendar(target_date)
                return result
            finally:
                await sync_service.close()
        
        result = run_async(_run())
        
        logger.info(
            "Calendar sync completed",
            hotel_id=hotel_id,
            success=result.success,
            records_processed=result.records_processed,
            records_created=result.records_created,
            records_updated=result.records_updated,
            duration_ms=result.duration_ms,
        )
        
        return {
            "success": result.success,
            "operation": result.operation,
            "hotel_id": result.hotel_id,
            "records_processed": result.records_processed,
            "records_created": result.records_created,
            "records_updated": result.records_updated,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }
        
    except Exception as e:
        logger.error("Calendar sync task failed", hotel_id=hotel_id, error=str(e))
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    retry_jitter=True,
)
def sync_categories(self, hotel_id: str, target_date: Optional[str] = None):
    """
    Sync categories from OtelMS.
    Runs hourly via Celery Beat.
    """
    logger.info("Starting categories sync task", hotel_id=hotel_id)
    
    try:
        sync_service = SyncService(
            hotel_id=hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        
        async def _run():
            await sync_service.initialize()
            try:
                result = await sync_service.sync_categories(target_date)
                return result
            finally:
                await sync_service.close()
        
        result = run_async(_run())
        
        logger.info(
            "Categories sync completed",
            hotel_id=hotel_id,
            success=result.success,
            records_processed=result.records_processed,
            duration_ms=result.duration_ms,
        )
        
        return {
            "success": result.success,
            "operation": result.operation,
            "hotel_id": result.hotel_id,
            "records_processed": result.records_processed,
            "records_created": result.records_created,
            "records_updated": result.records_updated,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }
        
    except Exception as e:
        logger.error("Categories sync task failed", hotel_id=hotel_id, error=str(e))
        raise


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=600,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
    retry_jitter=True,
)
def sync_full(self, hotel_id: str, target_date: Optional[str] = None):
    """
    Full sync: calendar + categories + reservation details.
    Runs daily at 3 AM via Celery Beat.
    """
    logger.info("Starting full sync task", hotel_id=hotel_id)
    
    try:
        sync_service = SyncService(
            hotel_id=hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        
        async def _run():
            await sync_service.initialize()
            try:
                result = await sync_service.full_sync(target_date)
                return result
            finally:
                await sync_service.close()
        
        result = run_async(_run())
        
        logger.info(
            "Full sync completed",
            hotel_id=hotel_id,
            success=result.success,
            records_processed=result.records_processed,
            records_created=result.records_created,
            records_updated=result.records_updated,
            duration_ms=result.duration_ms,
        )
        
        return {
            "success": result.success,
            "operation": result.operation,
            "hotel_id": result.hotel_id,
            "records_processed": result.records_processed,
            "records_created": result.records_created,
            "records_updated": result.records_updated,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }
        
    except Exception as e:
        logger.error("Full sync task failed", hotel_id=hotel_id, error=str(e))
        raise


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def sync_reservation_details(self, hotel_id: str, target_date: str, reservation_ids: Optional[list[str]] = None):
    """
    Sync specific reservation details.
    Can be triggered manually or after calendar sync finds new reservations.
    """
    logger.info("Starting reservation details sync", hotel_id=hotel_id, target_date=target_date)
    
    try:
        sync_service = SyncService(
            hotel_id=hotel_id,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            headless=settings.scraper_headless,
            base_domain=settings.otelms_base_domain,
        )
        
        async def _run():
            await sync_service.initialize()
            try:
                result = await sync_service.sync_reservation_details(target_date, reservation_ids)
                return result
            finally:
                await sync_service.close()
        
        result = run_async(_run())
        
        logger.info(
            "Reservation details sync completed",
            hotel_id=hotel_id,
            success=result.success,
            records_processed=result.records_processed,
            duration_ms=result.duration_ms,
        )
        
        return {
            "success": result.success,
            "operation": result.operation,
            "hotel_id": result.hotel_id,
            "records_processed": result.records_processed,
            "records_created": result.records_created,
            "records_updated": result.records_updated,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }
        
    except Exception as e:
        logger.error("Reservation details sync task failed", hotel_id=hotel_id, error=str(e))
        raise


@shared_task
def health_check():
    """Simple health check task for monitoring."""
    from otelms.domain.repositories.database import db
    from otelms.utils.cache import cache
    
    checks = {}
    
    # Check DB
    try:
        async def _check_db():
            async with db.session() as session:
                await session.execute("SELECT 1")
        asyncio.run(_check_db())
        checks["database"] = True
    except Exception:
        checks["database"] = False
    
    # Check Cache
    try:
        asyncio.run(cache.get("_health_check"))
        checks["cache"] = True
    except Exception:
        checks["cache"] = False
    
    all_healthy = all(checks.values())
    
    return {
        "healthy": all_healthy,
        "checks": checks,
    }


@shared_task
def cleanup_old_sync_logs(days: int = 30):
    """Cleanup old sync logs to prevent database bloat."""
    from datetime import datetime, timedelta, timezone
    from otelms.domain.repositories.database import get_db_session
    from otelms.domain.entities import SyncLog
    from sqlalchemy import delete
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    async def _run():
        async with get_db_session() as session:
            stmt = delete(SyncLog).where(SyncLog.started_at < cutoff)
            result = await session.execute(stmt)
            return result.rowcount
    
    deleted = run_async(_run())
    logger.info("Cleaned up old sync logs", deleted_count=deleted, days=days)
    return {"deleted": deleted}