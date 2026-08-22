"""Resuelve configuración de proxy para scraping según entorno y hotel.

Soporta múltiples backends:
- 'tor': SOCKS5 local (Tor) — para navegación post-login (NO para login)
- 'scrape_do': Scrape.do API directa (https://scrape.do?api_key=***&url=...)
- 'webshare': Webshare proxy rotativo (HTTP proxy)
"""

from dataclasses import dataclass

from otelms.config.settings import get_settings
from otelms.domain.entities import Hotel
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ProxyConfig:
    """Configuración de proxy para una operación de scraping."""

    url: str | None = None  # URL del proxy o endpoint API
    enabled: bool = False
    backend: str = "none"  # none | tor | scrape_do | webshare

    def is_tor_enabled(self) -> bool:
        return self.enabled and self.backend == "tor" and self.url is not None

    def is_http_proxy(self) -> bool:
        """Proxy HTTP(S) con auth (Scrape.do, Webshare)."""
        return self.enabled and self.backend in ("scrape_do", "webshare")


def resolve_proxy(hotel: Hotel | None = None) -> ProxyConfig:
    """Decide si usar proxy para scraping según configuración.

    Lógica:
    - Solo en desarrollo (APP_ENV=development) Y USE_PROXY=true → proxy
    - En producción (APP_ENV=production) → sin proxy
    - En staging → sin proxy
    """
    settings = get_settings()

    # Solo en desarrollo y con USE_PROXY habilitado
    if not (settings.is_dev and settings.use_proxy):
        return ProxyConfig(url=None, enabled=False)

    backend = settings.proxy_backend.lower()

    if backend == "scrape_do":
        # Scrape.do: usar API directa (https://scrape.do?api_key=***&url=TARGET)
        # Funciona como reverse proxy: la key se pasa como query param.
        if settings.scraper_api_key:
            api_base = f"https://scrape.do?api_key={settings.scraper_api_key}"
            logger.info("Using Scrape.do API for scraping", proxy=api_base[:30])
            return ProxyConfig(url=api_base, enabled=True, backend="scrape_do")

    elif backend == "webshare":
        # Webshare: HTTP/HTTPS proxy rotativo
        if settings.scraper_api_key:
            proxy_url = f"http://scraper:{settings.scraper_api_key}@proxy.webshare.io:80"
            logger.info("Using Webshare proxy for scraping")
            return ProxyConfig(url=proxy_url, enabled=True, backend="webshare")

    elif backend == "tor":
        # Tor SOCKS5 (local) — solo para navegación, no login
        proxy_url = settings.proxy_url
        logger.info("Using Tor SOCKS5 proxy for scraping")
        return ProxyConfig(url=proxy_url, enabled=True, backend="tor")

    return ProxyConfig(url=None, enabled=False)