"""
Servicio de sincronización - Orquesta scraping + persistencia en BD.
"""
import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import Hotel
from otelms.domain.repositories import (
    CategoryRepository,
    GuestRepository,
    HotelRepository,
    PaymentRepository,
    ReservationRepository,
    RoomRepository,
    ServiceRepository,
    SyncLogRepository,
)
from otelms.domain.repositories.database import get_db_session
from otelms.scraping.exceptions import AuthenticationError
from otelms.scraping.folio_extract import parse_folio
from otelms.scraping.http_calendar import fetch_calendar_html
from otelms.scraping.http_folio import FolioClient
from otelms.scraping.orchestrator import ScrapingOrchestrator
from otelms.scraping.parsers import CalendarParser
from otelms.utils.crypto import credential_encryption  # For password decryption
from otelms.utils.logging import get_logger
from otelms.utils.telemetry import record_celery_metric

logger = get_logger(__name__)


def _pick(detail: dict, *keys: str) -> object:
    """Primer valor no vacío entre varias claves y varios sitios.

    Los datos llegan en dos formas: la celda del calendario los trae en
    plano ('guest_name', 'check_in'), el modal los anidaba en
    'basic_info'/'accommodation', y la tabla de campos del calendario los
    usa como etiquetas de su idioma ('Llegada', 'Huésped'). Los tres se
    miran aquí para que el sync no dependa de cuál de los dos caminos
    trajo la reserva.
    """
    sources = (
        detail,
        detail.get("basic_info") or {},
        detail.get("accommodation") or {},
        detail.get("fields") or {},
    )
    for key in keys:
        for source in sources:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


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

        self._orchestrator = ScrapingOrchestrator(
            hotel_id=hotel_id,
            username=username,
            password=password,
            headless=headless,
            base_domain=base_domain,
        )
        self._initialized = False

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
        """Inicializa orquestador y verifica BD."""
        if self._initialized:
            return

        await self._orchestrator.initialize()

        # Verificar que el hotel existe en BD
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
        return await hotel_repo.create(**hotel.__dict__)

    async def close(self) -> None:
        """Cierra recursos."""
        await self._orchestrator.close()
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
                )
                return parsed
            logger.warning("HTTP calendar vacío, probando browser")
        except Exception as e:
            logger.warning("HTTP calendar falló, probando browser", error=str(e))

        scrape_result = await self._orchestrator.scrape_calendar(target_date)
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

        scrape_result = await self._orchestrator.scrape_categories(target_date)
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
                created, updated = await self._persist_calendar(session, calendar_data)
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated

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
        """Sincronización completa: calendario + categorías + detalles."""
        start = self._start_timer()
        result = SyncResult(
            operation="full_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()

            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "full")

            # 1. Calendario
            calendar_result = await self.sync_calendar(target_date)
            result.records_processed += calendar_result.records_processed
            result.records_created += calendar_result.records_created
            result.records_updated += calendar_result.records_updated
            result.errors.extend(calendar_result.errors)

            if not calendar_result.success:
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("full_sync", "error", self._elapsed_ms(start) / 1000)
                return result

            # 2. Categorías
            cat_result = await self.sync_categories(target_date)
            result.records_processed += cat_result.records_processed
            result.records_created += cat_result.records_created
            result.records_updated += cat_result.records_updated
            result.errors.extend(cat_result.errors)

            # 3. Detalles (reservas ocupadas del calendario)
            if calendar_result.records_processed > 0:
                # Obtener IDs de reservas del resultado del calendario
                # (en una implementación real, pasar los IDs)
                detail_result = await self.sync_reservation_details(
                    target_date or date.today().isoformat()
                )
                result.records_processed += detail_result.records_processed
                result.records_created += detail_result.records_created
                result.records_updated += detail_result.records_updated
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
    ) -> tuple[int, int]:
        """Persiste datos del calendario en BD."""
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

            # Datos de reserva
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
                "total_price": cell.get("balance"),
                "currency": "USD",
                "source": cell.get("fields", {}).get("Fuente"),
                "notes": cell.get("comments"),
            }

            res, is_new, was_updated = await res_repo.upsert_from_scraper(
                self.hotel_id, res_data
            )
            if is_new:
                created += 1
            elif was_updated:
                updated += 1

        await session.commit()
        return created, updated

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
        """Cargos + precio por noche, en las columnas del modelo Service.

        El modelo pide `date` obligatoria y los cargos de tipo
        'Alojamiento' la traen vacía (se imputan a las noches de la
        reserva, que llegan en room_charges). Por eso se encadenan ambas
        listas y se rellena la fecha con la primera noche disponible.

        El id se compone con el de la reserva porque `Service.id` es clave
        primaria **sola**: los números de línea del folio (49839, 49842...)
        se repiten entre reservas distintas y sin el prefijo el INSERT
        revienta con duplicate key. El id de la noche tenía el mismo
        problema: dos reservas con una noche el mismo día lo compartían.
        """
        first_night = next(
            (c.get("date") for c in folio.get("room_charges", []) if c.get("date")),
            None,
        )

        rows = []
        # Se construyen dicts nuevos en vez de retocar los del folio: si
        # se mutaran, la fecha heredada se colaría en el folio original y
        # en la siguiente reserva que compartiese ese parseo.
        for svc in folio.get("services", []):
            rows.append((svc.get("date") or first_night, svc))
        for charge in folio.get("room_charges", []):
            rows.append((
                charge.get("date"),
                {
                    "id": f"night-{charge.get('date')}",
                    "name": charge.get("description") or "Alojamiento",
                    "legal_entity": None,
                    "description": "Precio por noche",
                    "price": charge.get("amount"),
                    "amount": charge.get("amount"),
                },
            ))

        out = []
        for raw_date, src in rows:
            parsed_date = _parse_otelms_datetime(raw_date)
            if parsed_date is None:
                # Sin fecha no hay fila: Service.date es NOT NULL.
                continue
            price = src.get("price") or src.get("amount") or Decimal("0")
            total = src.get("amount") or src.get("price") or Decimal("0")
            out.append({
                # Service llama title/total a lo que el parser llama
                # name/amount; mandar ambas rompería el constructor.
                "id": f"{reservation_id}-{src.get('id')}",
                "title": src.get("name") or "Consumo",
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

            res_data = {
                "id": str(res_id),
                "hotel_id": self.hotel_id,
                "room_id": _pick(detail, "room", "room_id"),
                "guest_id": guest_id,
                "check_in": _parse_otelms_datetime(
                    _pick(detail, "check_in", "llegada")
                ),
                "check_out": _parse_otelms_datetime(
                    _pick(detail, "check_out", "salida")
                ),
                "status": _pick(detail, "status") or 1,
                "adults": _pick(detail, "guest_count", "cantidad de huéspedes") or 1,
                "children": 0,
                "babies": 0,
                "total_price": _pick(detail, "total", "balance"),
                "currency": "USD",
                "source": _pick(detail, "source", "Fuente", "channel"),
                "notes": _pick(detail, "comments", "comentarios"),
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
            except Exception as exc:
                logger.warning(
                    "Folio parse failed", reservation_id=res_id, error=str(exc)
                )
                continue

            services = self._service_rows(folio, str(res_id))
            if services:
                services_total += await svc_repo.bulk_upsert(str(res_id), services)

            payments = self._payment_rows(folio, str(res_id))
            if payments:
                payments_total += await pmt_repo.bulk_upsert(str(res_id), payments)

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
