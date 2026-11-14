"""
Configuración centralizada con Pydantic-Settings.
Carga variables de entorno desde .env y valida tipos.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    # ============================================================
    # APP
    # ============================================================
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_workers: int = Field(default=1, alias="APP_WORKERS")

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    # ============================================================
    # API SECURITY
    # ============================================================
    api_key: str = Field(default="changeme-secure-api-key-here", alias="API_KEY")
    api_key_header: str = Field(default="X-API-Key", alias="API_KEY_HEADER")
    api_key_required: bool = Field(default=True, alias="API_KEY_REQUIRED")

    jwt_secret_key: str = Field(
        default="changeme-jwt-secret-key-min-32-chars", alias="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def _jwt_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return v

    # ============================================================
    # DATABASE
    # ============================================================
    database_url: str = Field(
        default="sqlite+aiosqlite:///./otelms.db", alias="DATABASE_URL"
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=3600, alias="DB_POOL_RECYCLE")

    # ============================================================
    # REDIS
    # ============================================================
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_max_connections: int = Field(default=20, alias="REDIS_MAX_CONNECTIONS")
    redis_socket_timeout: int = Field(default=5, alias="REDIS_SOCKET_TIMEOUT")
    redis_socket_connect_timeout: float = Field(
        default=0.5, alias="REDIS_SOCKET_CONNECT_TIMEOUT"
    )

    # ============================================================
    # API GATEWAY / FEATURE FLAGS (Fase 1 vs Fase 2)
    # ============================================================
    api_enable_read_public: bool = Field(default=True, alias="API_ENABLE_READ_PUBLIC")
    api_enable_internal_sync: bool = Field(default=True, alias="API_ENABLE_INTERNAL_SYNC")
    api_enable_write_actions: bool = Field(default=False, alias="API_ENABLE_WRITE_ACTIONS")
    api_enable_admin_routes: bool = Field(default=True, alias="API_ENABLE_ADMIN_ROUTES")
    api_enable_legacy_routes: bool = Field(default=False, alias="API_ENABLE_LEGACY_ROUTES")

    # ============================================================
    # CELERY
    # ============================================================
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1", alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND"
    )
    celery_task_serializer: str = Field(default="json", alias="CELERY_TASK_SERIALIZER")
    celery_result_serializer: str = Field(
        default="json", alias="CELERY_RESULT_SERIALIZER"
    )
    celery_accept_content: str = Field(default="json", alias="CELERY_ACCEPT_CONTENT")
    celery_timezone: str = Field(default="UTC", alias="CELERY_TIMEZONE")
    celery_enable_utc: bool = Field(default=True, alias="CELERY_ENABLE_UTC")
    celery_task_track_started: bool = Field(
        default=True, alias="CELERY_TASK_TRACK_STARTED"
    )
    celery_task_time_limit: int = Field(default=300, alias="CELERY_TASK_TIME_LIMIT")
    celery_worker_prefetch_multiplier: int = Field(
        default=1, alias="CELERY_WORKER_PREFETCH_MULTIPLIER"
    )
    celery_worker_max_tasks_per_child: int = Field(
        default=100, alias="CELERY_WORKER_MAX_TASKS_PER_CHILD"
    )

    # ============================================================
    # SCRAPING - OTELMS
    # ============================================================
    otelms_base_domain: str = Field(default="otelms.com", alias="OTELMS_BASE_DOMAIN")
    otelms_login_path: str = Field(default="/login/DoLogIn/", alias="OTELMS_LOGIN_PATH")
    otelms_calendar_path: str = Field(
        default="/reservation_c2/calendar", alias="OTELMS_CALENDAR_PATH"
    )
    otelms_detail_path: str = Field(
        default="/reservation_c2/folio/", alias="OTELMS_DETAIL_PATH"
    )
    otelms_guest_path: str = Field(
        default="/reservation_c2/guestfolio/", alias="OTELMS_GUEST_PATH"
    )
    otelms_edit_path: str = Field(
        default="/reservation_c2/edit/", alias="OTELMS_EDIT_PATH"
    )

    otelms_default_hotel_id: str = Field(
        default="18330", alias="OTELMS_DEFAULT_HOTEL_ID"
    )
    otelms_default_username: str = Field(
        default="gerencia@harmonyhotelgroup.com", alias="OTELMS_DEFAULT_USERNAME"
    )
    otelms_default_password: str = Field(default="changeme", alias="OTELMS_DEFAULT_PASSWORD")

    scraper_headless: bool = Field(default=True, alias="SCRAPER_HEADLESS")
    scraper_timeout_ms: int = Field(default=60000, alias="SCRAPER_TIMEOUT_MS")
    scraper_navigation_timeout_ms: int = Field(
        default=45000, alias="SCRAPER_NAVIGATION_TIMEOUT_MS"
    )
    scraper_selector_timeout_ms: int = Field(
        default=20000, alias="SCRAPER_SELECTOR_TIMEOUT_MS"
    )
    scraper_wait_after_navigation_ms: int = Field(
        default=500, alias="SCRAPER_WAIT_AFTER_NAVIGATION_MS"
    )
    scraper_max_retries: int = Field(default=3, alias="SCRAPER_MAX_RETRIES")
    scraper_retry_base_delay: float = Field(default=1.0, alias="SCRAPER_RETRY_BASE_DELAY")
    scraper_retry_max_delay: float = Field(default=30.0, alias="SCRAPER_RETRY_MAX_DELAY")
    scraper_retry_jitter: bool = Field(default=True, alias="SCRAPER_RETRY_JITTER")

    scraper_rate_limit_requests_per_minute: int = Field(
        default=30, alias="SCRAPER_RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    scraper_rate_limit_burst: int = Field(default=5, alias="SCRAPER_RATE_LIMIT_BURST")
    scraper_rate_limit_per_hotel: bool = Field(
        default=True, alias="SCRAPER_RATE_LIMIT_PER_HOTEL"
    )
    scraper_verify_ssl: bool = Field(default=True, alias="SCRAPER_VERIFY_SSL")

    browser_pool_size: int = Field(default=2, alias="BROWSER_POOL_SIZE")
    browser_pool_max_idle_seconds: int = Field(
        default=300, alias="BROWSER_POOL_MAX_IDLE_SECONDS"
    )
    browser_headless: bool = Field(default=True, alias="BROWSER_HEADLESS")
    browser_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        alias="BROWSER_USER_AGENT",
    )
    browser_viewport_width: int = Field(default=1920, alias="BROWSER_VIEWPORT_WIDTH")
    browser_viewport_height: int = Field(default=1080, alias="BROWSER_VIEWPORT_HEIGHT")
    browser_locale: str = Field(default="es-ES", alias="BROWSER_LOCALE")
    browser_timezone: str = Field(default="America/Guayaquil", alias="BROWSER_TIMEZONE")

    # Proxy para pruebas de scraping (solo desarrollo)
    use_proxy: bool = Field(default=False, alias="USE_PROXY")
    proxy_backend: str = Field(
        default="scrape_do",
        alias="PROXY_BACKEND",
    )  # none | tor | scrape_do | webshare
    proxy_url: str = Field(
        default="socks5h://host.docker.internal:9050",
        alias="PROXY_URL",
    )
    scraper_api_key: str = Field(default="", alias="SCRAPER_API_KEY")

    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_ttl_seconds: int = Field(default=1800, alias="CACHE_TTL_SECONDS")
    cache_max_size_mb: int = Field(default=100, alias="CACHE_MAX_SIZE_MB")

    # ============================================================
    # LOGGING
    # ============================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    log_format: Literal["json", "console"] = Field(default="json", alias="LOG_FORMAT")
    log_file: str = Field(default="logs/otelms.log", alias="LOG_FILE")
    log_rotation: str = Field(default="1 day", alias="LOG_ROTATION")
    log_retention: str = Field(default="7 days", alias="LOG_RETENTION")
    log_compression: str = Field(default="gz", alias="LOG_COMPRESSION")

    # ============================================================
    # OBSERVABILITY
    # ============================================================
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")
    metrics_path: str = Field(default="/metrics", alias="METRICS_PATH")

    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="otelms-api", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_exporter_otlp_headers: str = Field(
        default="", alias="OTEL_EXPORTER_OTLP_HEADERS"
    )

    # ============================================================
    # SYNC SCHEDULE
    # ============================================================
    sync_calendar_cron: str = Field(default="*/15 * * * *", alias="SYNC_CALENDAR_CRON")
    sync_categories_cron: str = Field(default="0 * * * *", alias="SYNC_CATEGORIES_CRON")
    sync_full_detail_cron: str = Field(default="0 3 * * *", alias="SYNC_FULL_DETAIL_CRON")
    display_timezone: str = Field(default="America/Guayaquil", alias="DISPLAY_TIMEZONE")

    # ============================================================
    # HELPERS
    # ============================================================
    def get_log_path(self) -> Path:
        """Ruta absoluta del archivo de log."""
        path = Path(self.log_file)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_database_url_sync(self) -> str:
        """URL de BD para migraciones (sync driver)."""
        if self.database_url.startswith("sqlite+aiosqlite"):
            return self.database_url.replace("sqlite+aiosqlite", "sqlite")
        if self.database_url.startswith("postgresql+asyncpg"):
            return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configuración (cacheado)."""
    return Settings()


# Instancia global para uso directo
settings = get_settings()
