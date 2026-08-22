"""
Browser pool con Camoufox para scraping anti-detect.
Maneja pool de navegadores, contextos y páginas con lifecycle management.
"""
import asyncio
import contextlib
from dataclasses import dataclass, field

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, BrowserContext, Page

from otelms.config.settings import settings
from otelms.scraping.exceptions import BrowserError
from otelms.scraping.proxy_resolver import resolve_proxy
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BrowserInstance:
    """Wrapper para una instancia de navegador con metadatos."""
    browser: Browser
    context: BrowserContext
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    last_used: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    in_use: bool = False
    page_count: int = 0

    @property
    def idle_seconds(self) -> float:
        return asyncio.get_event_loop().time() - self.last_used


class BrowserPool:
    """
    Pool de navegadores Camoufox para scraping concurrente.
    - Reutiliza instancias para evitar overhead de lanzamiento
    - Limpia instancias inactivas periódicamente
    - Maneja recuperación ante crashes
    """

    def __init__(
        self,
        pool_size: int = 2,
        max_idle_seconds: int = 300,
        headless: bool = True,
    ):
        self.pool_size = pool_size
        self.max_idle_seconds = max_idle_seconds
        self.headless = headless

        self._browser: Browser | None = None
        self._camoufox_context: AsyncCamoufox | None = None
        self._instances: list[BrowserInstance] = []
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._shutdown = False

    async def initialize(self) -> None:
        """Inicializa el pool creando las instancias iniciales."""
        logger.info("Initializing browser pool", pool_size=self.pool_size)
        # AsyncCamoufox is an async context manager, use it directly
        self._camoufox_context = AsyncCamoufox(headless=self.headless)
        assert self._camoufox_context is not None
        self._browser = await self._camoufox_context.__aenter__()

        # Crear instancias iniciales
        for _ in range(self.pool_size):
            await self._create_instance()

        # Iniciar task de limpieza
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _create_instance(self) -> BrowserInstance:
        """Crea una nueva instancia de navegador con contexto."""
        if not self._browser:
            raise BrowserError("Browser not initialized")

        proxy_config = resolve_proxy()
        # Crear nuevo contexto en el mismo navegador
        context_kwargs = {
            "user_agent": settings.browser_user_agent,
            "viewport": {
                "width": settings.browser_viewport_width,
                "height": settings.browser_viewport_height,
            },
            "locale": settings.browser_locale,
            "timezone_id": settings.browser_timezone,
        }
        # Añadir proxy si está habilitado
        if proxy_config.enabled and proxy_config.url:
            # Playwright usa formato socks5:// para SOCKS5 (no socks5h)
            # socks5h resuelve DNS en el proxy, socks5 en local
            proxy_server = proxy_config.url.replace("socks5h://", "socks5://")
            context_kwargs["proxy"] = {"server": proxy_server}
            logger.debug("Creating browser context with Tor proxy", proxy=proxy_server)

        context = await self._browser.new_context(**context_kwargs)
        # Configurar timeouts por defecto
        context.set_default_timeout(settings.scraper_timeout_ms)
        context.set_default_navigation_timeout(settings.scraper_navigation_timeout_ms)

        instance = BrowserInstance(browser=self._browser, context=context)
        self._instances.append(instance)
        logger.debug("Browser instance created", total=len(self._instances))
        return instance

    @contextlib.asynccontextmanager
    async def acquire(self) -> Page:
        """
        Adquiere una página del pool (context manager).
        Uso:
            async with pool.acquire() as page:
                await page.goto(url)
        """
        instance = await self._get_available_instance()
        instance.in_use = True
        instance.last_used = asyncio.get_event_loop().time()

        page = await instance.context.new_page()
        instance.page_count += 1

        try:
            yield page
        except Exception as e:
            logger.error("Error in acquired page", error=str(e))
            # Si la página falla, cerrarla y crear nueva
            with contextlib.suppress(Exception):
                await page.close()
            instance.page_count -= 1
            raise
        finally:
            instance.in_use = False
            instance.last_used = asyncio.get_event_loop().time()
            with contextlib.suppress(Exception):
                await page.close()
            instance.page_count -= 1

    async def _get_available_instance(self) -> BrowserInstance:
        """Obtiene una instancia disponible o crea nueva si hay espacio."""
        async with self._lock:
            # Buscar instancia libre
            for instance in self._instances:
                if not instance.in_use and instance.page_count == 0:
                    # Verificar que el browser sigue vivo
                    if await self._is_healthy(instance):
                        return instance
                    else:
                        logger.warning("Unhealthy instance detected, recreating")
                        await self._replace_instance(instance)
                        return await self._get_available_instance()

            # Si todas están en uso pero hay espacio en el pool
            if len(self._instances) < self.pool_size:
                return await self._create_instance()

            # Esperar a que se libere una
            while True:
                for instance in self._instances:
                    if not instance.in_use and instance.page_count == 0:
                        if await self._is_healthy(instance):
                            return instance
                        else:
                            await self._replace_instance(instance)
                await asyncio.sleep(0.1)

    async def _is_healthy(self, instance: BrowserInstance) -> bool:
        """Verifica si la instancia sigue saludable."""
        try:
            # Test rápido: nueva página y cierre
            page = await instance.context.new_page()
            await page.close()
            return True
        except Exception as e:
            logger.warning("Instance health check failed", error=str(e))
            return False

    async def _replace_instance(self, old_instance: BrowserInstance) -> None:
        """Reemplaza una instancia fallida."""
        try:
            await old_instance.context.close()
            await old_instance.browser.close()
        except Exception:
            pass

        if old_instance in self._instances:
            self._instances.remove(old_instance)

        await self._create_instance()

    async def _cleanup_loop(self) -> None:
        """Loop periódico para limpiar instancias inactivas."""
        while not self._shutdown:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_idle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup loop error", error=str(e))

    async def _cleanup_idle(self) -> None:
        """Cierra instancias que llevan mucho tiempo inactivas."""
        async with self._lock:
            to_remove = []

            for instance in self._instances:
                if (
                    not instance.in_use
                    and instance.page_count == 0
                    and instance.idle_seconds > self.max_idle_seconds
                    and len(self._instances) > 1  # Mantener al menos 1
                ):
                    to_remove.append(instance)

            for instance in to_remove:
                logger.info("Removing idle browser instance", idle_seconds=instance.idle_seconds)
                try:
                    await instance.context.close()
                    await instance.browser.close()
                except Exception:
                    pass
                self._instances.remove(instance)

    async def get_status(self) -> dict:
        """Estado actual del pool."""
        return {
            "pool_size": self.pool_size,
            "active_instances": len(self._instances),
            "instances": [
                {
                    "in_use": inst.in_use,
                    "page_count": inst.page_count,
                    "idle_seconds": round(inst.idle_seconds, 1),
                }
                for inst in self._instances
            ],
        }

    async def close(self) -> None:
            """Cierra todo el pool."""
            logger.info("Closing browser pool")
            self._shutdown = True

            if self._cleanup_task:
                self._cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._cleanup_task

            for instance in self._instances:
                try:
                    await instance.context.close()
                    await instance.browser.close()
                except Exception as e:
                    logger.warning("Error closing instance", error=str(e))

            self._instances.clear()

            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None

            if hasattr(self, '_camoufox_context') and self._camoufox_context:
                try:
                    await self._camoufox_context.__aexit__(None, None, None)
                except Exception:
                    pass
                self._camoufox_context = None


# Instancia global
browser_pool = BrowserPool(
    pool_size=settings.browser_pool_size,
    max_idle_seconds=settings.browser_pool_max_idle_seconds,
    headless=settings.browser_headless,
)


async def get_browser_pool() -> BrowserPool:
    """Dependency para FastAPI."""
    return browser_pool
