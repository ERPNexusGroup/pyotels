"""Utilidades de zona horaria: ejecución/almacenamiento en UTC, visualización en Ecuador (America/Guayaquil)."""
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from otelms.config.settings import settings

_ECUADOR_FALLBACK = timezone(timedelta(hours=-5), name="ECT")


def get_display_tz() -> timezone | ZoneInfo:
    """Retorna la zona horaria de visualización configurada (default: America/Guayaquil)."""
    tz_name = getattr(settings, "display_timezone", "America/Guayaquil") or "America/Guayaquil"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return _ECUADOR_FALLBACK


def utc_now() -> datetime:
    """Hora actual del servidor en UTC (aware)."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Normaliza un datetime naive o aware a UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_ecuador(dt: datetime) -> datetime:
    """Convierte un datetime (UTC si es naive) a la hora local de Ecuador (-05:00)."""
    return ensure_utc(dt).astimezone(get_display_tz())


def to_ecuador_iso(dt: datetime | None) -> str | None:
    """Formatea un datetime en ISO-8601 con offset de Ecuador (-05:00)."""
    if dt is None:
        return None
    return to_ecuador(dt).isoformat()
