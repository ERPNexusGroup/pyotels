"""
Orquestador principal de scraping.
Coordina browser pool, auth, extractors, parsers y rate limiting.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from otelms.config.constants import OtelMSUrls
from otelms.domain.entities import Hotel
from otelms.scraping.auth import OtelMSAuth
from otelms.scraping.browser import browser_pool
from otelms.scraping.exceptions import (
    AuthenticationError,
    NavigationError,
)
from otelms.scraping.extractors import (
    CalendarExtractor,
    GuestDetailExtractor,
    ModalExtractor,
    ReservationDetailExtractor,
)
from otelms.scraping.parsers import (
    CalendarParser,
    GuestDetailParser,
    ModalParser,
    ReservationDetailParser,
)
from otelms.scraping.rate_limiter import rate_limiter
from otelms.utils.logging import get_logger
from otelms.utils.telemetry import record_scraping_metric

logger = get_logger(__name__)


@dataclass
class ScrapingResult:
    """Resultado de una operación de scraping."""
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: int = 0
    hotel_id: str = ""
    operation: str = ""


class ScrapingOrchestrator:
    """
    Orquestador principal para scraping de OtelMS.
    Maneja el ciclo de vida completo: browser, auth, rate limit, extract, parse.
    """

    def __init__(
        self,
        hotel_id: str,
        username: str,
        password: str,
        headless: bool = True,
        base_domain: str = "otelms.com",
        rate_limit_rpm: int = 30,
        burst: int = 5,
        timeout_ms: int = 60000,
        navigation_timeout_ms: int = 45000,
        selector_timeout_ms: int = 20000,
    ):
        self.hotel_id = hotel_id
        self.username = username
        self.password = password
        self.headless = headless
        self.base_domain = base_domain
        self.urls = OtelMSUrls(base_domain, hotel_id)

        # Per-hotel config
        self.rate_limit_rpm = rate_limit_rpm
        self.burst = burst
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.selector_timeout_ms = selector_timeout_ms

        self._auth = OtelMSAuth(hotel_id, username, password, base_domain)
        self._initialized = False
        self._start_time = 0

    @classmethod
    async def from_hotel(cls, hotel: "Hotel") -> "ScrapingOrchestrator":
        """Crea orquestador desde entidad Hotel con config de BD."""
        # Note: hotel.password_hash is hashed, need to decrypt
        # For now, we'll need a way to get the plain password
        # This will be handled by the SyncService which has access to decrypted credentials
        return cls(
            hotel_id=hotel.id,
            username=hotel.username,
            password="",  # Will be set by caller with decrypted password
            headless=hotel.scraper_headless,
            base_domain=hotel.custom_domain if hotel.use_custom_domain else hotel.domain,
            rate_limit_rpm=hotel.scraper_rate_limit_rpm,
            burst=hotel.scraper_burst,
            timeout_ms=hotel.scraper_timeout_ms,
            navigation_timeout_ms=hotel.scraper_navigation_timeout_ms,
            selector_timeout_ms=hotel.scraper_selector_timeout_ms,
        )

    async def initialize(self) -> None:
        """Inicializa browser pool y autenticación."""
        if self._initialized:
            return

        logger.info("Initializing scraping orchestrator", hotel_id=self.hotel_id)

        # Inicializar browser pool
        await browser_pool.initialize()

        # Inicializar rate limiter
        await rate_limiter.client.ping()

        # Inicializar auth
        async with browser_pool.acquire() as page:
            await self._auth.login(page.context)

        self._initialized = True
        logger.info("Scraping orchestrator initialized", hotel_id=self.hotel_id)

    async def close(self) -> None:
        """Cierra recursos."""
        await self._auth.close_http_client()
        # No cerrar browser_pool aquí (es global)
        self._initialized = False
        logger.info("Scraping orchestrator closed", hotel_id=self.hotel_id)

    def _start_timer(self) -> None:
        self._start_time = datetime.utcnow().timestamp() * 1000

    def _elapsed_ms(self) -> int:
        return int((datetime.utcnow().timestamp() * 1000) - self._start_time)

    def _make_result(
        self,
        success: bool,
        data: Any = None,
        error: str | None = None,
        operation: str = "",
    ) -> ScrapingResult:
        return ScrapingResult(
            success=success,
            data=data,
            error=error,
            duration_ms=self._elapsed_ms(),
            hotel_id=self.hotel_id,
            operation=operation,
        )

    # ============================================================
    # CALENDAR / GRID
    # ============================================================
    async def scrape_calendar(self, target_date: str | None = None) -> ScrapingResult:
        """Scraping del calendario (grid de reservas)."""
        self._start_timer()
        logger.info("Scraping calendar", hotel_id=self.hotel_id, date=target_date)

        try:
            await self._ensure_ready()

            async with browser_pool.acquire() as page:
                # Rate limiting - use per-hotel config
                await rate_limiter.wait_if_needed(self.hotel_id)

                # Asegurar sesión válida
                await self._auth.ensure_valid_session(page.context)

                # Extraer
                extractor = CalendarExtractor(page, self.urls)
                await extractor.navigate(target_date)

                # Obtener HTML y parsear
                html = await page.content()
                parsed = CalendarParser.parse_grid(html, target_date)

                # Enriquecer con categorías
                categories = CalendarParser.parse_categories(html)
                parsed["categories"] = categories

            result = self._make_result(True, parsed, operation="calendar")
            record_scraping_metric("calendar", self.hotel_id, "success", result.duration_ms / 1000)
            return result

        except AuthenticationError as e:
            record_scraping_metric("calendar", self.hotel_id, "auth_error", 0)
            return self._make_result(False, error=f"Auth failed: {e}", operation="calendar")
        except NavigationError as e:
            record_scraping_metric("calendar", self.hotel_id, "nav_error", 0)
            return self._make_result(False, error=f"Navigation failed: {e}", operation="calendar")
        except Exception as e:
            logger.error("Calendar scraping failed", error=str(e))
            record_scraping_metric("calendar", self.hotel_id, "error", 0)
            return self._make_result(False, error=str(e), operation="calendar")

    async def scrape_categories(self, target_date: str | None = None) -> ScrapingResult:
        """Scraping solo de categorías y habitaciones."""
        self._start_timer()
        logger.info("Scraping categories", hotel_id=self.hotel_id)

        try:
            await self._ensure_ready()

            async with browser_pool.acquire() as page:
                await rate_limiter.wait_if_needed(self.hotel_id)
                await self._auth.ensure_valid_session(page.context)

                extractor = CalendarExtractor(page, self.urls)
                await extractor.navigate(target_date)

                categories = await extractor.extract_categories()

            result = self._make_result(
                True,
                [{"id": c.id, "name": c.name, "rooms": c.rooms} for c in categories],
                operation="categories",
            )
            record_scraping_metric("categories", self.hotel_id, "success", result.duration_ms / 1000)
            return result

        except Exception as e:
            logger.error("Categories scraping failed", error=str(e))
            record_scraping_metric("categories", self.hotel_id, "error", 0)
            return self._make_result(False, error=str(e), operation="categories")

    # ============================================================
    # RESERVATION DETAILS
    # ============================================================
    async def scrape_reservation_detail(self, reservation_id: str) -> ScrapingResult:
        """Scraping de detalle completo de una reserva."""
        self._start_timer()
        logger.info("Scraping reservation detail", hotel_id=self.hotel_id, reservation_id=reservation_id)

        try:
            await self._ensure_ready()

            async with browser_pool.acquire() as page:
                await rate_limiter.wait_if_needed(self.hotel_id)
                await self._auth.ensure_valid_session(page.context)

                extractor = ReservationDetailExtractor(page, self.urls)
                await extractor.navigate(reservation_id)

                # Info básica
                basic_info = await extractor.extract_basic_info()

                # Modal de alojamiento
                accommodation = {}
                if await extractor.click_edit_button():
                    modal_data = await extractor.extract_accommodation_modal()
                    accommodation = ReservationDetailParser.parse_accommodation_modal(modal_data["html"])
                await extractor.close_modal_if_open()

                # Huésped (si hay guest_id en basic_info)
                guest_data = {}
                guest_id = basic_info.get("fields", {}).get("Huésped")
                if guest_id:
                    # Extraer guest_id real del enlace
                    page_html = await page.content()
                    match = re.search(r'/guestfolio/(\d+)', page_html)
                    if match:
                        guest_id = match.group(1)
                        guest_extractor = GuestDetailExtractor(page, self.urls)
                        await guest_extractor.navigate(guest_id)
                        guest_html = await page.content()
                        guest_data = GuestDetailParser.parse(guest_html)

            result = {
                "reservation_id": reservation_id,
                "basic_info": basic_info,
                "accommodation": accommodation,
                "guest": guest_data,
            }

            result_obj = self._make_result(True, result, operation="reservation_detail")
            record_scraping_metric("reservation_detail", self.hotel_id, "success", result_obj.duration_ms / 1000)
            return result_obj

        except Exception as e:
            logger.error("Reservation detail scraping failed", reservation_id=reservation_id, error=str(e))
            record_scraping_metric("reservation_detail", self.hotel_id, "error", 0)
            return self._make_result(False, error=str(e), operation="reservation_detail")

    async def scrape_reservation_details(
        self,
        target_date: str,
        reservation_ids: list[str] | None = None,
    ) -> ScrapingResult:
        """Scraping de detalles de múltiples reservas."""
        self._start_timer()
        logger.info("Scraping multiple reservation details", hotel_id=self.hotel_id, date=target_date)

        try:
            await self._ensure_ready()

            async with browser_pool.acquire() as page:
                await rate_limiter.wait_if_needed(self.hotel_id)
                await self._auth.ensure_valid_session(page.context)

                # Si no se pasan IDs, obtener del calendario
                if not reservation_ids:
                    extractor = CalendarExtractor(page, self.urls)
                    await extractor.navigate(target_date)
                    grid = await extractor.extract_calendar_grid(target_date)
                    reservation_ids = [c.reservation_id for c in grid if c.reservation_id]

                logger.info("Found reservations to detail", count=len(reservation_ids))

                # Modal extractor para obtener todos los modales
                modal_extractor = ModalExtractor(page)
                modals = await modal_extractor.extract_all_modals(reservation_ids)

                # Parsear modales
                parsed_modals = ModalParser.parse_all(modals)

            result = self._make_result(True, parsed_modals, operation="reservation_details")
            record_scraping_metric("reservation_details", self.hotel_id, "success", result.duration_ms / 1000)
            return result

        except Exception as e:
            logger.error("Multiple reservation details scraping failed", error=str(e))
            record_scraping_metric("reservation_details", self.hotel_id, "error", 0)
            return self._make_result(False, error=str(e), operation="reservation_details")

    # ============================================================
    # FULL SYNC
    # ============================================================
    async def full_scrape(self, target_date: str | None = None) -> ScrapingResult:
        """Scraping completo: calendario + categorías + detalles."""
        self._start_timer()
        logger.info("Starting full scrape", hotel_id=self.hotel_id)

        try:
            await self._ensure_ready()

            results = {}

            # 1. Calendario
            calendar_result = await self.scrape_calendar(target_date)
            results["calendar"] = calendar_result.data if calendar_result.success else None
            if not calendar_result.success:
                return self._make_result(False, results, error="Calendar failed", operation="full")

            # 2. Categorías (ya incluidas en calendar)
            results["categories"] = calendar_result.data.get("categories", []) if calendar_result.data else []

            # 3. Detalles de reservas (sample o todas)
            if calendar_result.data and calendar_result.data.get("cells"):
                occupied = [c for c in calendar_result.data["cells"] if c.get("cell_status") == "occupied"]
                res_ids = [c.get("reservation_id") for c in occupied if c.get("reservation_id")]

                if res_ids:
                    # Limitar a primeros N para no saturar
                    max_details = 20
                    if len(res_ids) > max_details:
                        logger.info("Limiting detail scraping", total=len(res_ids), limit=max_details)
                        res_ids = res_ids[:max_details]

                    detail_result = await self.scrape_reservation_details(target_date, res_ids)
                    results["reservation_details"] = detail_result.data if detail_result.success else []

            result = self._make_result(True, results, operation="full_scrape")
            record_scraping_metric("full_scrape", self.hotel_id, "success", result.duration_ms / 1000)
            return result

        except Exception as e:
            logger.error("Full scrape failed", error=str(e))
            record_scraping_metric("full_scrape", self.hotel_id, "error", 0)
            return self._make_result(False, error=str(e), operation="full_scrape")

    # ============================================================
    # HELPERS
    # ============================================================
    async def _ensure_ready(self) -> None:
        """Asegura que el orquestador está inicializado."""
        if not self._initialized:
            await self.initialize()

    async def get_status(self) -> dict:
        """Estado actual del orquestador."""
        pool_status = await browser_pool.get_status()
        rate_status = await rate_limiter.get_status(self.hotel_id)

        return {
            "hotel_id": self.hotel_id,
            "initialized": self._initialized,
            "authenticated": self._auth.is_logged_in(),
            "browser_pool": pool_status,
            "rate_limiter": rate_status,
        }
