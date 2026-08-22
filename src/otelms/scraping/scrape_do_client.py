"""Wrapper para requests httpx que usa Scrape.do API directa.

En lugar de usar proxy HTTP, envuelve cada URL con:
  https://scrape.do?api_key=***&url=<URL_codificada>

Esto funciona con GET y POST (la key se pasa como query param al API).
"""
import asyncio
import httpx
from otelms.config.settings import settings
from otelms.scraping.proxy_resolver import resolve_proxy
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class ScrapeDoClient:
    """httpx.AsyncClient que routa todo tráfico vía Scrape.do API directa."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.scraper_api_key
        self._client: httpx.AsyncClient | None = None

    def _wrap_url(self, url: str) -> str:
        """Envuelve URL objetivo con Scrape.do API."""
        from urllib.parse import quote

        encoded = quote(url, safe="")
        return f"https://scrape.do?api_key={self.api_key}&url={encoded}"

    async def get(self, url: str, **kwargs) -> httpx.Response:
        if not self._client:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=False,  # Scrape.do maneja redirecciones
                headers=kwargs.pop("headers", {}),
            )
        wrapped = self._wrap_url(url)
        # Pasamos headers originales de regreso
        if "headers" in kwargs:
            self._client.headers.update(kwargs["headers"])
        return await self._client.get(wrapped, **{k: v for k, v in kwargs.items() if k != "headers"})

    async def post(self, url: str, **kwargs) -> httpx.Response:
        if not self._client:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=False,
                headers=kwargs.pop("headers", {}),
            )
        wrapped = self._wrap_url(url)
        return await self._client.post(wrapped, **kwargs)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None