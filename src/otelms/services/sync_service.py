"""
Servicio de sincronización - Orquesta scraping + persistencia en BD.
"""
import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import Hotel, HousekeepingStatus, Room
from otelms.domain.repositories import (
    CategoryAvailabilityRepository,
    CategoryRepository,
    ChannelRateRepository,
    GuestRepository,
    HotelRepository,
    PaymentRepository,
    ReservationChangeHistoryRepository,
    ReservationNightRateRepository,
    ReservationRepository,
    RoomAvailabilityRepository,
    RoomRepository,
    ServiceRepository,
    SyncLogRepository,
)
from otelms.domain.repositories.database import get_db_session
from otelms.scraping.exceptions import AuthenticationError
from otelms.scraping.folio_deep_extract import parse_folio_complete
from otelms.scraping.folio_extract import parse_folio
from otelms.scraping.http_calendar import fetch_calendar_html
from otelms.scraping.http_folio import FolioClient
from otelms.scraping.parsers import CalendarParser
from otelms.scraping.setup_extract import SetupExtractor
from otelms.services.setup_sync_service import SetupSyncService
from otelms.utils.crypto import credential_encryption  # For password decryption
from otelms.utils.logging import get_logger
from otelms.utils.telemetry import record_celery_metric

logger = get_logger(__name__)


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if v.lower() in {"", "0", "---", "–", "—", "n/a", "na", "none", "null"}:
            return None
        return v
    return value


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        text = str(value).strip().replace(",", ".")
        if text == "" or text.lower() in {"0", "---", "na", "none", "null"}:
            # 0 can be valid for amounts; treat textual placeholders as None only
            if text.lower() in {"", "---", "na", "none", "null"}:
                return None
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
        if cleaned in {"", ".", "-", "-."}:
            return None
        return Decimal(cleaned)
    except Exception:
        return None


def _compute_total_price(folio: dict[str, Any], night_rates_data: list[dict[str, Any]] | None = None) -> Decimal | None:
    """Calcula precio total desde cargos reales del folio (o night rates) sin usar balance."""
    total = Decimal("0")
    has_any = False
    night_rates_data = night_rates_data or []
    # Preferir cargos reales del folio (services/charges)
    for svc in folio.get("services", []) or []:
        amt = svc.get("amount") or svc.get("total") or svc.get("price")
        d = _decimal_or_none(amt)
        if d is not None:
            total += d
            has_any = True
    # Si no hubo cargos parseados, usar night rates como fallback
    if not has_any and night_rates_data:
        for nr in night_rates_data:
            d = _decimal_or_none(nr.get("amount") or nr.get("price"))
            if d is not None:
                total += d
                has_any = True
    # Fallback adicional: room_charges del folio simple si existen
    if not has_any:
        for rc in folio.get("room_charges", []) or []:
            d = _decimal_or_none(rc.get("amount"))
            if d is not None:
                total += d
                has_any = True
    return total if has_any else None


def _reservation_id(detail: dict) -> str | None:
    """Identificador de reserva de una entrada del sync.

    El calendario lo llama 'reservation_id', el modal 'reservation_number'.
    Que se lean los dos en un solo sitio es lo que evita que uno de los dos
    caminos termine buscando folios por una clave que nunca va a existir:
    con la clave equivocada el folio salía vacío y el sync reportaba
    éxito sin haber guardado ningún cargo.
    """
    value = (
        detail.get("reservation_id")
        or detail.get("reservation_number")
        or detail.get("id")
    )
    return str(value) if value else None


def _cell_date(cell: dict) -> str:
    """Fecha de una celda del calendario; '' si no la tiene.

    La celda sintética que se crea para una reserva pedida a mano no trae
    fecha, y tiene que quedar por detrás de cualquier celda real.
    """
    return str(cell.get("date") or cell.get("check_in") or "")


def _parse_otelms_datetime(value: object) -> datetime | None:
    """Normaliza a datetime lo que traiga el folio.

    El folio mezcla '2026-09-27' con '2026-08-10 03:31:00'. Las columnas
    del modelo son DateTime(timezone=True), así que se devuelve UTC.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    logger.warning("Fecha de folio ilegible, se descarta", value=text)
    return None


@dataclass
class HotelSyncResult:
    """Resultado de sincronización de un hotel."""

    hotel_id: str
    success: bool
    error: str | None = None
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    duration_ms: int = 0


@dataclass
class MultiHotelSyncResult:
    """Resultado agregado de sincronización multi-hotel."""

    total_hotels: int
    successful: int
    failed: int
    details: list[HotelSyncResult] = field(default_factory=list)


@dataclass
class SyncResult:
    """Resultado de una operación de sincronización."""
    operation: str
    hotel_id: str
    success: bool
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    services_persisted: int = 0
    payments_persisted: int = 0
    availability_persisted: int = 0


class SyncService:
    """
    Servicio de sincronización principal.
    Coordina scraping de OtelMS y persistencia en base de datos.
    """

    def __init__(
        self,
        hotel_id: str,
        username: str,
        password: str,
        headless: bool = True,
        base_domain: str = "otelms.com",
    ):
        self.hotel_id = hotel_id
        self.username = username
        self.password = password
        self.headless = headless
        self.base_domain = base_domain

        self._orchestrator: Any = None
        self._initialized = False

    async def _ensure_orchestrator(self) -> Any:
        """Inicializa ScrapingOrchestrator solo si se requiere fallback browser real."""
        if self._orchestrator is None:
            from otelms.scraping.orchestrator import ScrapingOrchestrator

            self._orchestrator = ScrapingOrchestrator(
                hotel_id=self.hotel_id,
                username=self.username,
                password=self.password,
                headless=self.headless,
                base_domain=self.base_domain,
            )
            await self._orchestrator.initialize()
        return self._orchestrator

    @classmethod
    async def from_hotel(cls, hotel: Hotel) -> "SyncService":
        """Crea servicio de sincronización desde entidad Hotel con credenciales descifradas."""
        if hotel.encrypted_password:
            password = credential_encryption.decrypt(hotel.encrypted_password)
        else:
            # Fallback legacy: password_hash es SHA-256 no descifrable; se usa tal cual
            # (hoteles creados antes de que existiera encrypted_password).
            password = hotel.password_hash
        return cls(
            hotel_id=hotel.id,
            username=hotel.username,
            password=password,
            headless=hotel.scraper_headless,
            base_domain=hotel.custom_domain or hotel.domain,
        )

    async def initialize(self) -> None:
        """Inicialización ligera: verifica/crea hotel en BD (sin navegador)."""
        if self._initialized:
            return

        async with get_db_session() as session:
            hotel_repo = HotelRepository(session)
            hotel = await hotel_repo.get_by_id(self.hotel_id)
            if not hotel:
                logger.warning("Hotel not in DB, creating", hotel_id=self.hotel_id)
                await self._create_hotel_in_db(session)

        self._initialized = True
        logger.info("Sync service initialized", hotel_id=self.hotel_id)

    async def _create_hotel_in_db(self, session: AsyncSession) -> Hotel:
        """Crea hotel en BD si no existe."""

        hotel_repo = HotelRepository(session)
        pwd_hash = hashlib.sha256(self.password.encode()).hexdigest()

        hotel = Hotel(
            id=self.hotel_id,
            name="Harmony Hotel Group",
            domain=self.base_domain,
            username=self.username,
            password_hash=pwd_hash,
            is_active=True,
        )
        # Use explicit fields to avoid SQLAlchemy internal attributes
        return await hotel_repo.create(
            id=hotel.id,
            name=hotel.name,
            domain=hotel.domain,
            username=hotel.username,
            password_hash=hotel.password_hash,
            is_active=hotel.is_active,
        )

    async def close(self) -> None:
        """Cierra recursos."""
        if self._orchestrator is not None:
            await self._orchestrator.close()
            self._orchestrator = None
        self._initialized = False

    def _start_timer(self) -> float:
        return datetime.now(UTC).timestamp() * 1000

    def _elapsed_ms(self, start: float) -> int:
        return int((datetime.now(UTC).timestamp() * 1000) - start)

    # ============================================================
    # SYNC OPERATIONS
    # ============================================================

    async def _scrape_calendar_data(self, target_date: str | None = None) -> dict:
        """Grid del calendario: HTTP directo primero, browser como fallback.

        El HTML es server-rendered; HTTP es más rápido y robusto. El fallback
        conserva el comportamiento anterior (browser vía orchestrator).
        """
        try:
            html = await fetch_calendar_html(
                self.hotel_id, self.username, self.password, self.base_domain, target_date
            )
            parsed = CalendarParser.parse_grid(html, target_date)
            if parsed.get("cells") or parsed.get("categories"):
                logger.info(
                    "Calendar scraped over HTTP",
                    cells=len(parsed["cells"]),
                    categories=len(parsed["categories"]),
                    availability=len(parsed.get("availability", [])),
                )
                return parsed
            logger.warning("HTTP calendar vacío, probando browser")
        except Exception as e:
            logger.warning("HTTP calendar falló, probando browser", error=str(e))

        scrape_result = await (await self._ensure_orchestrator()).scrape_calendar(target_date)
        if not scrape_result.success:
            raise RuntimeError(scrape_result.error or "Unknown error")
        data: dict = scrape_result.data
        return data

    async def _scrape_categories_data(self, target_date: str | None = None) -> list[dict]:
        """Categorías: HTTP directo primero, browser como fallback."""
        try:
            html = await fetch_calendar_html(
                self.hotel_id, self.username, self.password, self.base_domain, target_date
            )
            categories = CalendarParser.parse_categories(html)
            if categories:
                logger.info("Categories scraped over HTTP", count=len(categories))
                return categories
            logger.warning("HTTP categories vacío, probando browser")
        except Exception as e:
            logger.warning("HTTP categories falló, probando browser", error=str(e))

        scrape_result = await (await self._ensure_orchestrator()).scrape_categories(target_date)
        if not scrape_result.success:
            raise RuntimeError(scrape_result.error or "Unknown error")
        data: list[dict] = scrape_result.data
        return data

    async def sync_calendar(self, target_date: str | None = None) -> SyncResult:
        """Sincroniza calendario (grid de reservas)."""
        start = self._start_timer()
        result = SyncResult(
            operation="calendar_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()

            # Log de sync
            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "calendar")

            # Scraping (HTTP directo primero, browser como fallback)
            try:
                calendar_data = await self._scrape_calendar_data(target_date)
            except Exception as e:
                result.errors.append(str(e))
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_calendar", "error", self._elapsed_ms(start) / 1000)
                return result

            # Persistir en BD
            async with get_db_session() as session:
                created, updated, availability = await self._persist_calendar(
                    session, calendar_data
                )
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated
                result.availability_persisted = availability

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(UTC)

            await self._complete_log(log.id, result)
            logger.info("Calendar sync completed", **result.__dict__)
            record_celery_metric("sync_calendar", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Calendar sync failed", error=str(e))
            if log:
                await self._complete_log(log.id, result)
            record_celery_metric("sync_calendar", "error", self._elapsed_ms(start) / 1000)

        return result

    async def sync_categories(self, target_date: str | None = None) -> SyncResult:
        """Sincroniza categorías y habitaciones."""
        start = self._start_timer()
        result = SyncResult(
            operation="categories_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()

            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "categories")

            # Scraping (HTTP directo primero, browser como fallback)
            try:
                categories_data = await self._scrape_categories_data(target_date)
            except Exception as e:
                result.errors.append(str(e))
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_categories", "error", self._elapsed_ms(start) / 1000)
                return result

            async with get_db_session() as session:
                created, updated = await self._persist_categories(session, categories_data)
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(UTC)

            await self._complete_log(log.id, result)
            logger.info("Categories sync completed", **result.__dict__)
            record_celery_metric("sync_categories", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Categories sync failed", error=str(e))
            if log:
                await self._complete_log(log.id, result)
            record_celery_metric("sync_categories", "error", self._elapsed_ms(start) / 1000)

        return result

    async def sync_reservation_details(
        self,
        target_date: str | None = None,
        reservation_ids: list[str] | None = None,
    ) -> SyncResult:
        """Sincroniza detalles de reservas: reserva, huésped, cargos y pagos.

        Va por HTTP entero. Ni el modal ni el folio necesitan browser: el
        calendario y el folio son server-rendered. El browser se queda solo
        como respaldo, y de hecho hoy es la parte que peor funciona —el
        extractor de grilla del navegador devuelve 0 celdas mientras que la
        grilla por HTTP devuelve las 13— así que dejarlo como camino
        principal hacía que este sync no guardara nada y aun así reportara
        success=True.
        """
        start = self._start_timer()
        result = SyncResult(
            operation="details_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()

            # El orquestador exige fecha; sin ella se sincroniza el día de
            # hoy, que es lo que quiere el CLI al llamarlo sin argumentos.
            if target_date is None:
                target_date = datetime.now(UTC).strftime("%Y-%m-%d")

            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "detail")

            details = await self._reservation_details(target_date, reservation_ids)
            if not details:
                result.errors.append(
                    f"Sin reservas que sincronizar para {target_date}"
                )
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_reservation_details", "error", self._elapsed_ms(start) / 1000)
                return result

            folios = await self._fetch_folios(details)

            async with get_db_session() as session:
                created, updated, svc_count, pmt_count = (
                    await self._persist_reservation_details(session, details, folios)
                )
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated
                result.services_persisted = svc_count
                result.payments_persisted = pmt_count

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(UTC)

            await self._complete_log(log.id, result)
            logger.info("Details sync completed", **result.__dict__)
            record_celery_metric("sync_reservation_details", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Details sync failed", error=str(e))
            if log:
                await self._complete_log(log.id, result)
            record_celery_metric("sync_reservation_details", "error", self._elapsed_ms(start) / 1000)

        return result

    async def full_sync(self, target_date: str | None = None) -> SyncResult:
        """Sincronización completa Fase 1: setup + calendario + channel_rates + folios + estado operativo."""
        start = self._start_timer()
        result = SyncResult(
            operation="full_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()
            if target_date is None:
                target_date = date.today().isoformat()

            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "full")

            # 1. Setup / maestros (categorías, habitaciones, dealers, métodos, servicios, hotel)
            try:
                setup_sync = SetupSyncService(self.hotel_id)
                await setup_sync.sync_all_setup()
            except Exception as e:
                result.errors.append(f"setup_sync: {e}")
                logger.warning("Setup sync failed in full_sync", error=str(e), hotel_id=self.hotel_id)

            # 2. Calendario + disponibilidad + locks (bg_padlock -> room_availability)
            calendar_result = await self.sync_calendar(target_date)
            result.records_processed += calendar_result.records_processed
            result.records_created += calendar_result.records_created
            result.records_updated += calendar_result.records_updated
            result.availability_persisted += calendar_result.availability_persisted
            result.errors.extend(calendar_result.errors)
            if not calendar_result.success:
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("full_sync", "error", self._elapsed_ms(start) / 1000)
                return result

            # 3. Categorías oficiales (setup ya las cubre, pero mantenemos consistencia con flujo previo)
            cat_result = await self.sync_categories(target_date)
            result.records_processed += cat_result.records_processed
            result.records_created += cat_result.records_created
            result.records_updated += cat_result.records_updated
            result.errors.extend(cat_result.errors)

            # 4. channel_rates desde /reservation_c2/price_calendar
            try:
                async with SetupExtractor(self.hotel_id) as extractor:
                    price_rates = await extractor.extract_price_calendar(target_date)
                async with get_db_session() as session:
                    rate_repo = ChannelRateRepository(session)
                    for r in price_rates:
                        try:
                            r_date = date.fromisoformat(str(r.get("date")))
                            channel = str(r.get("channel") or "Directa")
                            category_id = str(r.get("category_id") or "")
                            rate_id = str(r.get("rate_id") or "1")
                            if not category_id:
                                continue
                            price = Decimal(str(r.get("price") or "0"))
                            await rate_repo.upsert_rate(
                                hotel_id=self.hotel_id,
                                category_id=category_id,
                                rate_id=rate_id,
                                channel=channel,
                                target_date=r_date,
                                price=price,
                                currency="USD",
                            )
                        except Exception:
                            continue
                    await session.commit()
            except Exception as e:
                result.errors.append(f"price_calendar: {e}")
                logger.warning("Price calendar sync failed in full_sync", error=str(e), hotel_id=self.hotel_id)

            # 5. Estado operativo (/reservation_c2/status) + inicialización housekeeping_status diaria
            try:
                async with SetupExtractor(self.hotel_id) as extractor:
                    _status = await extractor.extract_status()
                # Inicializar housekeeping_status para habitaciones ocupadas y checkouts de hoy (si no existen)
                target_d = date.fromisoformat(target_date)
                async with get_db_session() as session:
                    room_rows = (await session.execute(select(Room.id).where(Room.hotel_id == self.hotel_id, Room.is_active == True))).scalars().all()  # noqa: E712
                    # Cargar estado existente de la fecha para no sobrescribir progreso/limpieza
                    existing_rows = (await session.execute(
                        select(HousekeepingStatus.room_id).where(
                            HousekeepingStatus.hotel_id == self.hotel_id,
                            HousekeepingStatus.date == target_d,
                        )
                    )).scalars().all()
                    existing = {str(r) for r in existing_rows}
                    for room_id in room_rows:
                        rid = str(room_id)
                        if rid in existing:
                            continue
                        session.add(HousekeepingStatus(
                            id=str(uuid.uuid4()),
                            hotel_id=self.hotel_id,
                            room_id=rid,
                            date=target_d,
                            status=0,
                            updated_by="sync_full",
                        ))
                    await session.commit()
            except Exception as e:
                result.errors.append(f"status_housekeeping: {e}")
                logger.warning("Status/housekeeping init failed in full_sync", error=str(e), hotel_id=self.hotel_id)

            # 6. Folios profundos (reservas activas/próximas del calendario del día objetivo)
            detail_result = await self.sync_reservation_details(target_date)
            result.records_processed += detail_result.records_processed
            result.records_created += detail_result.records_created
            result.records_updated += detail_result.records_updated
            result.services_persisted += detail_result.services_persisted
            result.payments_persisted += detail_result.payments_persisted
            result.errors.extend(detail_result.errors)

            result.success = len(result.errors) == 0
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(UTC)

            if log:
                await self._complete_log(log.id, result)
            logger.info("Full sync completed", **result.__dict__)
            record_celery_metric("full_sync", "success" if result.success else "error", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Full sync failed", error=str(e))
            if log:
                await self._complete_log(log.id, result)
            record_celery_metric("full_sync", "error", self._elapsed_ms(start) / 1000)

        return result

    # ============================================================
    # PERSISTENCE HELPERS
    # ============================================================

    async def _persist_calendar(
        self, session: AsyncSession, calendar_data: dict
    ) -> tuple[int, int, int]:
        """Persiste datos del calendario en BD.

        Devuelve (created, updated, availability). El tercer valor va aparte
        porque las celdas de disponibilidad no son ni creadas ni actualizadas
        de una en una: se reemplazan enteras por categoría (ver
        CategoryAvailabilityRepository.replace) y por eso no encajan en el
        contador mixto de categorías + habitaciones + reservas.
        """
        cells = calendar_data.get("cells", [])
        categories_data = calendar_data.get("categories", [])

        created = 0
        updated = 0

        # 1. Categorías y habitaciones
        cat_repo = CategoryRepository(session)
        room_repo = RoomRepository(session)

        for cat_data in categories_data:
            # Categoría
            cat, is_new = await cat_repo.upsert_with_rooms(
                self.hotel_id, cat_data
            )
            if is_new:
                created += 1
            else:
                updated += 1

            # Habitaciones
            for room_data in cat_data.get("rooms", []):
                room, is_new = await room_repo.upsert(
                    self.hotel_id, room_data
                )
                if is_new:
                    created += 1
                else:
                    updated += 1

        # 2. Reservas (celdas ocupadas)
        res_repo = ReservationRepository(session)
        guest_repo = GuestRepository(session)

        for cell in cells:
            if cell.get("cell_status") != "occupied":
                continue

            res_id = cell.get("reservation_id")
            if not res_id:
                continue

            # Huésped (básico)
            guest_id = None
            guest_name = cell.get("guest_name")
            if guest_name:
                guest, _ = await guest_repo.get_or_create_by_name(
                    self.hotel_id, guest_name
                )
                guest_id = guest.id

            # Datos de reserva (calendario: no usar balance como total_price)
            res_data = {
                "id": res_id,
                "hotel_id": self.hotel_id,
                "room_id": cell.get("room_id"),
                "guest_id": guest_id,
                "check_in": cell.get("check_in") or cell.get("date"),
                "check_out": cell.get("check_out") or cell.get("date"),
                "status": cell.get("reservation_status") or 1,
                "adults": cell.get("guest_count") or 1,
                "children": 0,
                "babies": 0,
                "total_price": _decimal_or_none(_pick(cell, "total_price")),
                "currency": "USD",
                "source": cell.get("fields", {}).get("Fuente"),
                "notes": _normalize_scalar(cell.get("comments")),
            }

            res, is_new, was_updated = await res_repo.upsert_from_scraper(
                self.hotel_id, res_data
            )
            if is_new:
                created += 1
            elif was_updated:
                updated += 1

        # 3. Disponibilidad por categoría y día.
        availability = await CategoryAvailabilityRepository(session).replace(
            self.hotel_id, calendar_data.get("availability", [])
        )

        # 4. Bloqueos bg_padlock -> room_availability (día específico por habitación)
        room_avail_repo = RoomAvailabilityRepository(session)
        for lock in calendar_data.get("locks", []) or []:
            lock_date_raw = lock.get("date")
            room_id = lock.get("room_id")
            if not lock_date_raw or not room_id:
                continue
            try:
                lock_date = date.fromisoformat(str(lock_date_raw))
            except ValueError:
                continue
            await room_avail_repo.upsert(
                hotel_id=self.hotel_id,
                room_id=str(room_id),
                start_date=lock_date,
                end_date=lock_date,
                is_blocked=True,
                reason="calendar_lock_bg_padlock",
            )

        await session.commit()
        return created, updated, availability

    async def _persist_categories(
        self, session: AsyncSession, categories_data: list[dict]
    ) -> tuple[int, int]:
        """Persiste categorías y habitaciones."""
        created = 0
        updated = 0

        cat_repo = CategoryRepository(session)
        room_repo = RoomRepository(session)

        for cat_data in categories_data:
            cat, is_new = await cat_repo.upsert_with_rooms(
                self.hotel_id, cat_data
            )
            if is_new:
                created += 1
            else:
                updated += 1

            for room_data in cat_data.get("rooms", []):
                room, is_new = await room_repo.upsert(
                    self.hotel_id, room_data
                )
                if is_new:
                    created += 1
                else:
                    updated += 1

        await session.commit()
        return created, updated

    async def _reservation_details(
        self, target_date: str, reservation_ids: list[str] | None = None
    ) -> list[dict]:
        """Reservas del día, una entrada por reserva, desde el calendario HTTP.

        Una reserva ocupa varias celdas (una por cada noche), así que se
        deduplica por resid: sin esto, una reserva de 16 noches se
        persistiría 16 veces y sus cargos se multiplicarían.

        La celda del calendario trae más que el modal (huésped, fechas,
        saldo, comentarios), así que el detalle sale mejor por aquí que
        abriendo 13 modales.
        """
        calendar = await self._scrape_calendar_data(target_date)
        cells = [
            c for c in calendar.get("cells", []) if c.get("reservation_id")
        ]

        by_res: dict[str, dict] = {}
        for cell in cells:
            res_id = str(cell["reservation_id"])
            if reservation_ids and res_id not in reservation_ids:
                continue
            existing = by_res.get(res_id)
            if existing is None or _cell_date(cell) < _cell_date(existing):
                # Ante varias celdas de la misma reserva gana la más
                # temprana: es la de llegada, y check_in debe ser la real.
                by_res[res_id] = cell

        if reservation_ids:
            # El caller pidió reservas concretas. Si el calendario del día
            # no las tiene (son de otra fecha), se añaden igualmente: su
            # folio se puede leer igual y de ahí salen los cargos.
            for res_id in reservation_ids:
                by_res.setdefault(res_id, {"reservation_id": res_id})

        return list(by_res.values())

    async def _fetch_folios(self, details: list[dict]) -> dict[str, str]:
        """Descarga el folio de cada reserva del lote.

        Ni el modal ni el calendario traen consumos ni pagos: eso solo está
        en /reservation_c2/folio/{id}. Sin esta llamada, services y payments
        no se pueden tener.

        Si el login falla no se tumba el sync. El calendario ya da la
        reserva y el huésped, que es lo importante; quedarse sin los cargos
        de un día es malo, pero perder el día entero también.
        """
        res_ids: list[str] = []
        for detail in details:
            res_id = _reservation_id(detail)
            if res_id and res_id not in res_ids:
                res_ids.append(res_id)

        if not res_ids:
            return {}

        try:
            async with FolioClient(
                self.hotel_id, self.username, self.password, self.base_domain
            ) as client:
                folios = await client.fetch_many(res_ids)
        except AuthenticationError as exc:
            logger.warning("Folio login failed, skipping charges", error=str(exc))
            return {}

        logger.info("Folios fetched", fetched=len(folios), requested=len(res_ids))
        return folios

    @staticmethod
    def _service_rows(folio: dict, reservation_id: str) -> list[dict]:
        """Cargos reales del folio en columnas del modelo Service.

        No se generan filas sintéticas por noche (`%-night-%`) porque el
        desglose por noche ya se persiste en `reservation_night_rates`.
        """
        out: list[dict] = []
        for src in folio.get("services", []):
            parsed_date = _parse_otelms_datetime(src.get("date"))
            if parsed_date is None:
                # Sin fecha no hay fila: Service.date es NOT NULL.
                continue
            price = src.get("price") or src.get("amount") or Decimal("0")
            total = src.get("amount") or src.get("total") or src.get("price") or Decimal("0")
            out.append({
                "id": f"{reservation_id}-{src.get('id')}",
                "title": src.get("name") or src.get("title") or "Consumo",
                "total": total,
                "price": price,
                "date": parsed_date,
                "quantity": src.get("quantity") or Decimal("1"),
                "description": src.get("description") or None,
                "legal_entity": src.get("legal_entity") or None,
            })
        return out

    @staticmethod
    def _payment_rows(folio: dict, reservation_id: str) -> list[dict]:
        """Pagos del folio en las columnas del modelo Payment.

        El id lleva el de la reserva delante por lo mismo que en los
        servicios: `Payment.id` es clave primaria sola.
        """
        rows = []
        for idx, pmt in enumerate(folio.get("payments", [])):
            payment_date = _parse_otelms_datetime(pmt.get("date") or pmt.get("created_at"))
            if payment_date is None:
                continue
            rows.append({
                # El folio numera los pagos, pero si viniera vacío mejor un
                # id sintético estable que perder el pago entero.
                "id": f"{reservation_id}-{pmt.get('id') or f'p{idx}'}",
                "date": payment_date,
                "amount": pmt.get("amount") or Decimal("0"),
                "method": pmt.get("method") or pmt.get("payment_type") or None,
                "reference": pmt.get("invoice_num") or pmt.get("id") or None,
                "status": pmt.get("card_status") or None,
                "card_number": pmt.get("card_number") or None,
                "card_type": pmt.get("payment_type") or None,
            })
        return rows

    async def _persist_reservation_details(
        self,
        session: AsyncSession,
        details: list[dict],
        folios: dict[str, str] | None = None,
    ) -> tuple[int, int, int, int]:
        """Persiste detalles completos de reservas, con sus cargos y pagos.

        Devuelve (created, updated, services, payments).
        """
        created = 0
        updated = 0
        services_total = 0
        payments_total = 0
        folios = folios or {}

        res_repo = ReservationRepository(session)
        guest_repo = GuestRepository(session)
        svc_repo = ServiceRepository(session)
        pmt_repo = PaymentRepository(session)
        rate_repo = ReservationNightRateRepository(session)
        history_repo = ReservationChangeHistoryRepository(session)

        for detail in details:
            res_id = _reservation_id(detail)
            if not res_id:
                continue

            # Las celdas del calendario traen los campos en plano. Se leen
            # aquí los de una reserva, pero `basic_info` se conserva para
            # quien venga del modal, que es lo que devolvía este sync antes.
            guest_data = detail.get("guest", {})
            guest_name = _pick(detail, "guest_name", "huésped", "guest")

            guest_id = None
            if guest_data:
                guest, _ = await guest_repo.upsert_from_scraper(
                    self.hotel_id, guest_data
                )
                guest_id = guest.id
            elif guest_name:
                guest, _ = await guest_repo.get_or_create_by_name(
                    self.hotel_id, str(guest_name)
                )
                guest_id = guest.id

            # Persistencia base desde calendario/detalle (sin balance como total_price)
            notes_val = _normalize_scalar(_pick(detail, "comments", "comentarios"))
            channel_res_id = _normalize_scalar(_pick(detail, "channel_reservation_id", "reservation_id_ota"))
            room_res_id = _normalize_scalar(_pick(detail, "room_reservation_id"))
            res_data = {
                "id": str(res_id),
                "hotel_id": self.hotel_id,
                "room_id": _pick(detail, "room", "room_id"),
                "guest_id": guest_id,
                "check_in": _parse_otelms_datetime(_pick(detail, "check_in", "llegada")),
                "check_out": _parse_otelms_datetime(_pick(detail, "check_out", "salida")),
                "status": _pick(detail, "status") or 1,
                "adults": _pick(detail, "guest_count", "cantidad de huéspedes") or 1,
                "children": 0,
                "babies": 0,
                "total_price": _decimal_or_none(_pick(detail, "total", "total_price")),
                "currency": "USD",
                "source": _normalize_scalar(_pick(detail, "source", "Fuente", "channel")),
                "notes": notes_val,
                "channel_reservation_id": channel_res_id,
                "room_reservation_id": room_res_id,
            }

            res, is_new, was_updated = await res_repo.upsert_from_scraper(
                self.hotel_id, res_data
            )
            if is_new:
                created += 1
            elif was_updated:
                updated += 1

            # Servicios y pagos vienen del folio, no del modal: es el
            # único sitio donde están. Sin folio descargado no hay nada
            # que guardar y la reserva se queda como estaba.
            folio_html = folios.get(str(res_id))
            if not folio_html:
                continue

            try:
                folio = parse_folio(folio_html, str(res_id))
                folio_deep = parse_folio_complete(folio_html, str(res_id))
            except Exception as exc:
                logger.warning(
                    "Folio parse failed", reservation_id=res_id, error=str(exc)
                )
                continue

            # Enriquecer huésped con datos del folio profundo (tel/email/género/nacimiento/nacionalidad)
            if guest_id:
                deep_client = folio_deep.get("client") or folio_deep.get("basic") or {}
                deep_guests = folio_deep.get("guests") or []
                primary = deep_guests[0] if deep_guests else {}
                guest_patch: dict[str, Any] = {}
                phone = _normalize_scalar(deep_client.get("phone") or primary.get("phone"))
                email = _normalize_scalar(deep_client.get("email") or primary.get("email"))
                gender = _normalize_scalar(primary.get("gender"))
                nationality = _normalize_scalar(primary.get("nationality"))
                birth = _normalize_scalar(primary.get("birth_date"))
                if phone:
                    guest_patch["phone"] = phone
                if email:
                    guest_patch["email"] = email
                if gender:
                    guest_patch["gender"] = gender
                if nationality:
                    guest_patch["nationality"] = nationality
                if birth:
                    try:
                        guest_patch["birth_date"] = _parse_otelms_datetime(birth)
                    except Exception:
                        pass
                # nombre completo si vino más detallado
                full_name = _normalize_scalar(deep_client.get("client_name") or primary.get("name"))
                if full_name and isinstance(full_name, str):
                    parts = full_name.split(" ", 1)
                    guest_patch.setdefault("first_name", parts[0])
                    if len(parts) > 1:
                        guest_patch.setdefault("last_name", parts[1])
                if guest_patch:
                    guest_patch["id"] = guest_id
                    guest_patch["hotel_id"] = self.hotel_id
                    await guest_repo.upsert_from_scraper(self.hotel_id, guest_patch)

            # Actualizar campos enriquecidos de la reserva desde el folio
            veh = folio_deep.get("vehicle") or {}
            if veh.get("brand") or veh.get("plate"):
                res.vehicle_brand = veh.get("brand") or res.vehicle_brand
                res.vehicle_color = veh.get("color") or res.vehicle_color
                res.vehicle_plate = veh.get("plate") or res.vehicle_plate

            stay_data = folio_deep.get("stay") or {}
            if stay_data.get("nights"):
                res.nights = stay_data.get("nights")
            if stay_data.get("rate"):
                res.rate_name = stay_data.get("rate")

            chn_data = folio_deep.get("channel") or {}
            ch_res = _normalize_scalar(chn_data.get("channel_reservation_id"))
            ch_room_res = _normalize_scalar(chn_data.get("room_reservation_id"))
            if ch_res:
                res.channel_reservation_id = ch_res
            if ch_room_res:
                res.room_reservation_id = ch_room_res

            deep_notes = folio_deep.get("notes") or []
            if isinstance(deep_notes, list) and deep_notes and not _normalize_scalar(res.notes):
                res.notes = "; ".join(
                    f"{n.get('author','')}: {n.get('text','')}".strip(": ")
                    for n in deep_notes
                    if isinstance(n, dict) and n.get("text")
                ) or res.notes
            elif isinstance(deep_notes, str) and deep_notes and not _normalize_scalar(res.notes):
                res.notes = deep_notes

            # Tarifas por noche (desglose día a día)
            night_rates_data = folio_deep.get("night_rates") or []
            if night_rates_data:
                await rate_repo.bulk_upsert(str(res_id), [
                    {
                        "date": nr["date"],
                        "rate_name": nr.get("rate_name"),
                        "price": nr.get("amount") or nr.get("price") or Decimal("0"),
                    }
                    for nr in night_rates_data if nr.get("date")
                ])

            # Historial de cambios y auditoría
            history_data = folio_deep.get("change_history") or []
            if history_data:
                await history_repo.bulk_upsert(str(res_id), [
                    {
                        "date": h.get("datetime") or h.get("date") or h.get("changed_at"),
                        "user": h.get("user") or h.get("user_name"),
                        "event_type": h.get("event_type") or h.get("type") or "change",
                        "action": h.get("action"),
                        "amount": h.get("amount"),
                        "description": h.get("description") or h.get("details"),
                    }
                    for h in history_data if (h.get("datetime") or h.get("date") or h.get("changed_at"))
                ])

            services = self._service_rows(folio, str(res_id))
            if services:
                services_total += await svc_repo.bulk_upsert(str(res_id), services)

            payments = self._payment_rows(folio, str(res_id))
            if payments:
                payments_total += await pmt_repo.bulk_upsert(str(res_id), payments)

            # total_price real (sin usar balance)
            computed_total = _compute_total_price(folio, night_rates_data)
            if computed_total is not None:
                res.total_price = computed_total

        await session.commit()
        return created, updated, services_total, payments_total

    # ============================================================
    # LOG HELPERS
    # ============================================================

    async def _complete_log(self, log_id: int, result: SyncResult) -> None:
        """Completa log de sincronización."""
        async with get_db_session() as session:
            sync_log_repo = SyncLogRepository(session)
            await sync_log_repo.complete_log(
                log_id=log_id,
                status="completed" if result.success else "failed",
                records_processed=result.records_processed,
                records_created=result.records_created,
                records_updated=result.records_updated,
                errors=result.errors if result.errors else None,
            )

    async def _ensure_ready(self) -> None:
        if not self._initialized:
            await self.initialize()

    async def get_sync_history(self, limit: int = 50) -> list[dict]:
        """Obtiene historial de sincronizaciones."""
        async with get_db_session() as session:
            sync_log_repo = SyncLogRepository(session)
            logs = await sync_log_repo.get_by_hotel(self.hotel_id, limit=limit)
            return [
                {
                    "id": log.id,
                    "sync_type": log.sync_type,
                    "status": log.status,
                    "started_at": log.started_at.isoformat() if log.started_at else None,
                    "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                    "duration_ms": log.duration_ms,
                    "records_processed": log.records_processed,
                    "records_created": log.records_created,
                    "records_updated": log.records_updated,
                    "error_count": log.error_count,
                }
                for log in logs
            ]

    async def sync_all_hotels(
        self,
        target_date: str | None = None,
        max_concurrent: int = 3,
    ) -> MultiHotelSyncResult:
        """Sincroniza todos los hoteles activos en paralelo con semáforo."""
        async with get_db_session() as session:
            hotel_repo = HotelRepository(session)
            hotels = await hotel_repo.get_active_with_config()

        semaphore = asyncio.Semaphore(max_concurrent)

        async def sync_one(hotel: Hotel) -> HotelSyncResult:
            async with semaphore:
                try:
                    svc = await SyncService.from_hotel(hotel)
                    await svc.initialize()
                    result = await svc.full_sync(target_date)
                    return HotelSyncResult(
                        hotel_id=hotel.id,
                        success=result.success,
                        error=result.errors[0] if result.errors else None,
                        records_processed=result.records_processed,
                        records_created=result.records_created,
                        records_updated=result.records_updated,
                        duration_ms=result.duration_ms,
                    )
                except Exception as e:
                    logger.error("Hotel sync failed", hotel_id=hotel.id, error=str(e))
                    return HotelSyncResult(hotel_id=hotel.id, success=False, error=str(e))
                finally:
                    await svc.close()

        results = await asyncio.gather(*[sync_one(h) for h in hotels])

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        return MultiHotelSyncResult(
            total_hotels=len(hotels),
            successful=successful,
            failed=failed,
            details=results,
        )
