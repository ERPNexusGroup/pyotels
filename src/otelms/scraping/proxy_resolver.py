"""Resuelve configuración de proxy para scraping según entorno y hotel."""

from dataclasses import dataclass

from otelms.config.settings import get_settings
from otelms.domain.entities import Hotel


@dataclass
class ProxyConfig:
    """Configuración de proxy para una operación de scraping."""
    url: str | None = None  # socks5h://127.0.0.1:9050 o None
    enabled: bool = False

    def is_tor_enabled(self) -> bool:
        return self.enabled and self.url is not None and self.url.startswith("socks5h")


def resolve_proxy(hotel: Hotel | None = None) -> ProxyConfig:
    """Decide si usar proxy Tor para este hotel.

    Lógica:
    - Solo en desarrollo (APP_ENV=development) Y USE_PROXY=true → Tor
    - En producción (APP_ENV=production) → sin proxy
    - En staging → sin proxy
    """
    settings = get_settings()

    # Solo en desarrollo y con USE_PROXY habilitado
    if settings.is_dev and settings.use_proxy:
        return ProxyConfig(
            url=settings.proxy_url,
            enabled=True,
        )

    return ProxyConfig(url=None, enabled=False)
