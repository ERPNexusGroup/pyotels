"""Test de conectividad con proxy Scrape.do."""
import asyncio
import httpx
from otelms.config.settings import get_settings
from otelms.scraping.proxy_resolver import resolve_proxy


async def test():
    settings = get_settings()
    proxy = resolve_proxy()
    print(f"USE_PROXY: {settings.use_proxy}")
    print(f"PROXY_BACKEND: {settings.proxy_backend}")
    print(f"SCRAPER_API_KEY len: {len(settings.scraper_api_key) if settings.scraper_api_key else 0}")
    print(f"ProxyConfig: {proxy}")

    if not proxy.enabled:
        print("Proxy deshabilitado — skipping")
        return

    async with httpx.AsyncClient(
        proxy=proxy.url,
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    ) as client:
        resp = await client.get("https://httpbin.org/ip")
        print(f"Status: {resp.status_code}")
        print(f"IP: {resp.json()}")


if __name__ == "__main__":
    asyncio.run(test())