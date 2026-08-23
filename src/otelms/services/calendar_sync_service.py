"""Servicio: extrae reservas del calendar OtelMS y persiste en BD."""
import asyncio
import hashlib
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.repositories import (
    GuestRepository,
    ReservationRepository,
    RoomRepository,
)
from otelms.config.settings import get_settings
from otelms.scraping.auth import OtelMSAuth
from otelms.scraping.calendar_extract import extract_all_reservations
from otelms.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class CalendarSyncService:
    """Orquesta extracción de calendar → persistencia en BD.

    Uso típico dentro de un contexto async con sesión DB:
        async with get_db_session() as db:
            svc = CalendarSyncService(db, hotel_id="18330")
            result = await svc.sync_reservations()
    """

    def __init__(self, db_session: AsyncSession, hotel_id: str):
        self.db = db_session
        self.hotel_id = hotel_id
        self.res_repo = ReservationRepository(db_session)
        self.guest_repo = GuestRepository(db_session)
        self.room_repo = RoomRepository(db_session)

    async def sync_reservations(self) -> dict:
        """Extrae y persiste todas las reservas del calendar.

        Returns:
            {"processed": int, "created": int, "updated": int, "errors": int}
        """
        from playwright.async_api import async_playwright

        auth = OtelMSAuth(hotel_id=self.hotel_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=settings.browser_user_agent,
            )

            # Login (usa session cache si existe)
            logged_in = await auth.ensure_valid_session(context)
            if not logged_in:
                logged_in = await auth.login(context)

            if not logged_in:
                await context.close()
                await browser.close()
                return {"processed": 0, "created": 0, "updated": 0, "errors": 1,
                        "error": "Login failed"}

            # Navegar al calendar
            page = await context.new_page()
            await page.goto(
                "https://desktop.otelms.com/reservation_c2/calendar",
                wait_until="networkidle",
                timeout=60000,
            )

            content = await page.content()
            cal_resp_text = content

            await context.close()
            await browser.close()

        # Extraer reservas del HTML
        scraped = extract_all_reservations(cal_resp_text)
        logger.info(f"Extracted {len(scraped)} reservations from calendar")

        # Persistir
        created = updated = errors = 0
        for res in scraped:
            try:
                data = self._map_to_db(res)
                _, is_new, was_updated = await self.res_repo.upsert_from_scraper(
                    self.hotel_id, data
                )
                if is_new:
                    created += 1
                elif was_updated:
                    updated += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error saving reservation {res.get('resid')}: {e}")

        return {
            "processed": len(scraped),
            "created": created,
            "updated": updated,
            "errors": errors,
        }

    def _map_to_db(self, scraped: dict) -> dict:
        """Mapea datos scrapeados al modelo Reservation."""
        check_in = self._parse_date(scraped.get("check_in", ""))
        check_out = self._parse_date(scraped.get("check_out", ""))

        data = {
            "id": str(scraped["resid"]),
            "check_in": check_in,
            "check_out": check_out,
            "status": scraped.get("status", 1),
            "adults": scraped.get("guest_count", 1) or 1,
            "source": scraped.get("channel", ""),
            "notes": scraped.get("comments", ""),
            "otelms_created_at": self._parse_date(scraped.get("created_at")),
            "otelms_updated_at": self._parse_date(scraped.get("modified_at")),
        }

        # Resolve guest_id
        guest_name = scraped.get("guest_name", "")
        if guest_name:
            data["guest_id"] = f"guest_{hashlib.sha256(guest_name.encode()).hexdigest()[:12]}"

        # Resolve room_id (fallback)
        room_type = scraped.get("room_type", "")
        data["room_id"] = room_type.lower().replace(" ", "_") if room_type else "room_default"

        return data

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parsea fechas OtelMS (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)."""
        if not date_str:
            return None
        date_str = date_str.strip()
        if date_str in ("0000-00-00", "0000-00-00 00:00:00"):
            return None
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None