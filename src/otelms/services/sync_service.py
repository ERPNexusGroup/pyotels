"""
Servicio de sincronización - Orquesta scraping + persistencia en BD.
"""
import asyncio
from datetime import datetime, date, timezone
from typing import Optional
from dataclasses import dataclass, field

from otelms.utils.logging import get_logger
from otelms.utils.telemetry import record_celery_metric
from otelms.scraping.orchestrator import ScrapingOrchestrator
from otelms.domain.repositories.database import get_db_session
from otelms.domain.repositories import (
    HotelRepository,
    CategoryRepository,
    RoomRepository,
    GuestRepository,
    ReservationRepository,
    ServiceRepository,
    PaymentRepository,
    SyncLogRepository,
)
from otelms.domain.entities import Hotel
from otelms.utils.crypto import credential_encryption  # For password decryption

logger = get_logger(__name__)


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
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


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
        password = credential_encryption.decrypt(hotel.password_hash)
        return cls(
            hotel_id=hotel.id,
            username=hotel.username,
            password=password,
            headless=hotel.scraper_headless,
            base_domain=hotel.custom_domain if hotel.use_custom_domain else hotel.domain,
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

    async def _create_hotel_in_db(self, session) -> Hotel:
        """Crea hotel en BD si no existe."""
        import hashlib

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
        return datetime.now(timezone.utc).timestamp() * 1000

    def _elapsed_ms(self, start: float) -> int:
        return int((datetime.now(timezone.utc).timestamp() * 1000) - start)

    # ============================================================
    # SYNC OPERATIONS
    # ============================================================

    async def sync_calendar(self, target_date: Optional[str] = None) -> SyncResult:
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

            # Scraping
            scrape_result = await self._orchestrator.scrape_calendar(target_date)

            if not scrape_result.success:
                result.errors.append(scrape_result.error or "Unknown error")
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_calendar", "error", self._elapsed_ms(start) / 1000)
                return result

            # Persistir en BD
            async with get_db_session() as session:
                created, updated = await self._persist_calendar(session, scrape_result.data)
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(timezone.utc)

            await self._complete_log(log.id, result)
            logger.info("Calendar sync completed", **result.__dict__)
            record_celery_metric("sync_calendar", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Calendar sync failed", error=str(e))
            await self._complete_log(log.id, result)
            record_celery_metric("sync_calendar", "error", self._elapsed_ms(start) / 1000)

        return result

    async def sync_categories(self, target_date: Optional[str] = None) -> SyncResult:
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

            scrape_result = await self._orchestrator.scrape_categories(target_date)

            if not scrape_result.success:
                result.errors.append(scrape_result.error or "Unknown error")
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_categories", "error", self._elapsed_ms(start) / 1000)
                return result

            async with get_db_session() as session:
                created, updated = await self._persist_categories(session, scrape_result.data)
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(timezone.utc)

            await self._complete_log(log.id, result)
            logger.info("Categories sync completed", **result.__dict__)
            record_celery_metric("sync_categories", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Categories sync failed", error=str(e))
            await self._complete_log(log.id, result)
            record_celery_metric("sync_categories", "error", self._elapsed_ms(start) / 1000)

        return result

    async def sync_reservation_details(
        self,
        target_date: str,
        reservation_ids: Optional[list[str]] = None,
    ) -> SyncResult:
        """Sincroniza detalles de reservas."""
        start = self._start_timer()
        result = SyncResult(
            operation="details_sync",
            hotel_id=self.hotel_id,
            success=False,
        )
        log = None

        try:
            await self._ensure_ready()

            async with get_db_session() as session:
                sync_log_repo = SyncLogRepository(session)
                log = await sync_log_repo.create_log(self.hotel_id, "detail")

            scrape_result = await self._orchestrator.scrape_reservation_details(
                target_date, reservation_ids
            )

            if not scrape_result.success:
                result.errors.append(scrape_result.error or "Unknown error")
                if log:
                    await self._complete_log(log.id, result)
                record_celery_metric("sync_reservation_details", "error", self._elapsed_ms(start) / 1000)
                return result

            async with get_db_session() as session:
                created, updated = await self._persist_reservation_details(
                    session, scrape_result.data
                )
                result.records_created = created
                result.records_updated = updated
                result.records_processed = created + updated

            result.success = True
            result.duration_ms = self._elapsed_ms(start)
            result.completed_at = datetime.now(timezone.utc)

            await self._complete_log(log.id, result)
            logger.info("Details sync completed", **result.__dict__)
            record_celery_metric("sync_reservation_details", "success", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Details sync failed", error=str(e))
            await self._complete_log(log.id, result)
            record_celery_metric("sync_reservation_details", "error", self._elapsed_ms(start) / 1000)

        return result

    async def full_sync(self, target_date: Optional[str] = None) -> SyncResult:
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
            result.completed_at = datetime.now(timezone.utc)

            if log:
                await self._complete_log(log.id, result)
            logger.info("Full sync completed", **result.__dict__)
            record_celery_metric("full_sync", "success" if result.success else "error", result.duration_ms / 1000)

        except Exception as e:
            result.errors.append(str(e))
            result.duration_ms = self._elapsed_ms(start)
            logger.error("Full sync failed", error=str(e))
            await self._complete_log(log.id, result)
            record_celery_metric("full_sync", "error", self._elapsed_ms(start) / 1000)

        return result

    # ============================================================
    # PERSISTENCE HELPERS
    # ============================================================

    async def _persist_calendar(
        self, session, calendar_data: dict
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
        self, session, categories_data: list[dict]
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

    async def _persist_reservation_details(
        self, session, details: list[dict]
    ) -> tuple[int, int]:
        """Persiste detalles completos de reservas."""
        created = 0
        updated = 0

        res_repo = ReservationRepository(session)
        guest_repo = GuestRepository(session)
        svc_repo = ServiceRepository(session)
        pmt_repo = PaymentRepository(session)

        for detail in details:
            res_id = detail.get("reservation_number") or detail.get("id")
            if not res_id:
                continue

            basic = detail.get("basic_info", {})
            accommodation = detail.get("accommodation", {})
            guest_data = detail.get("guest", {})

            # Huésped completo
            guest_id = None
            if guest_data:
                guest, _ = await guest_repo.upsert_from_scraper(
                    self.hotel_id, guest_data
                )
                guest_id = guest.id
            elif basic.get("guest_name"):
                guest, _ = await guest_repo.get_or_create_by_name(
                    self.hotel_id, basic["guest_name"]
                )
                guest_id = guest.id

            # Actualizar reserva con datos completos
            res_data = {
                "id": res_id,
                "hotel_id": self.hotel_id,
                "room_id": basic.get("room") or accommodation.get("room"),
                "guest_id": guest_id,
                "check_in": basic.get("check_in") or accommodation.get("check_in"),
                "check_out": basic.get("check_out") or accommodation.get("check_out"),
                "status": basic.get("status") or 1,
                "adults": basic.get("guest_count") or 1,
                "children": 0,
                "babies": 0,
                "total_price": basic.get("total") or basic.get("balance"),
                "currency": "USD",
                "source": basic.get("source"),
                "notes": basic.get("comments"),
            }

            res, is_new, was_updated = await res_repo.upsert_from_scraper(
                self.hotel_id, res_data
            )
            if is_new:
                created += 1
            elif was_updated:
                updated += 1

            # Servicios (si hay en accommodation o basic)
            services = []
            # TODO: extraer servicios del accommodation modal
            if services:
                await svc_repo.bulk_upsert(res_id, services)

            # Pagos
            payments = []
            # TODO: extraer pagos
            if payments:
                await pmt_repo.bulk_upsert(res_id, payments)

        await session.commit()
        return created, updated

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
        target_date: Optional[str] = None,
        max_concurrent: int = 3,
    ) -> "MultiHotelSyncResult":
        """Sincroniza todos los hoteles activos en paralelo con semáforo."""
        from dataclasses import dataclass, field

        @dataclass
        class HotelSyncResult:
            hotel_id: str
            success: bool
            error: Optional[str] = None
            records_processed: int = 0
            records_created: int = 0
            records_updated: int = 0
            duration_ms: int = 0

        @dataclass
        class MultiHotelSyncResult:
            total_hotels: int
            successful: int
            failed: int
            details: list[HotelSyncResult] = field(default_factory=list)

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
                        error=result.error,
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