"""
Configuración del paquete otelms.config
"""
from otelms.config.settings import settings, get_settings
from otelms.config.constants import (
    OtelMSSelectors,
    OtelMSUrls,
    ReservationStatus,
    CellStatus,
    Timeouts,
    Patterns,
)

__all__ = [
    "settings",
    "get_settings",
    "OtelMSSelectors",
    "OtelMSUrls",
    "ReservationStatus",
    "CellStatus",
    "Timeouts",
    "Patterns",
]