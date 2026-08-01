"""
Celery application configuration for background tasks.
"""
from celery import Celery
from celery.schedules import crontab

from otelms.config.settings import settings

# Create Celery app
celery_app = Celery("otelms")

# Configuration
celery_app.conf.update(
    # Broker & Backend
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    
    # Serialization
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content.split(",") if isinstance(settings.celery_accept_content, str) else ["json"],
    
    # Timezone
    timezone=settings.celery_timezone,
    enable_utc=settings.celery_enable_utc,
    
    # Task execution
    task_track_started=settings.celery_task_track_started,
    task_time_limit=settings.celery_task_time_limit,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    
    # Result backend
    result_expires=3600,
    result_compression="gzip",
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        "sync-calendar-every-15-min": {
            "task": "otelms.tasks.scraping_tasks.sync_calendar",
            "schedule": crontab(minute="*/15"),
            "args": (settings.otelms_default_hotel_id,),
        },
        "sync-categories-hourly": {
            "task": "otelms.tasks.scraping_tasks.sync_categories",
            "schedule": crontab(minute=0),
            "args": (settings.otelms_default_hotel_id,),
        },
        "sync-full-daily": {
            "task": "otelms.tasks.scraping_tasks.sync_full",
            "schedule": crontab(hour=3, minute=0),
            "args": (settings.otelms_default_hotel_id,),
        },
    },
    
    # Task routes (optional - for multiple queues)
    task_routes={
        "otelms.tasks.scraping_tasks.sync_calendar": {"queue": "scraping"},
        "otelms.tasks.scraping_tasks.sync_categories": {"queue": "scraping"},
        "otelms.tasks.scraping_tasks.sync_full": {"queue": "scraping"},
        "otelms.tasks.scraping_tasks.sync_reservation_details": {"queue": "scraping"},
    },
    
    # Worker config
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # Monitoring
    worker_disable_rate_limits=False,
)

# Auto-discover tasks
celery_app.autodiscover_tasks([
    "otelms.tasks.scraping_tasks",
])


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing."""
    print(f"Request: {self.request!r}")


def main():
    """Entry point for running Celery worker."""
    celery_app.start()


if __name__ == "__main__":
    main()