"""
Repositorio de Hotel.
"""
import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from otelms.domain.entities import (
    ApiKey,
    ApiKeyRole,
    Category,
    ChannelRate,
    Dealer,
    Guest,
    Hotel,
    HousekeepingStatus,
    Payment,
    PaymentMethod,
    Permission,
    PropertyService,
    Reservation,
    ReservationChangeHistory,
    ReservationNightRate,
    Role,
    Room,
    RoomAvailability,
    Service,
    SyncLog,
)
from otelms.domain.repositories.base import BaseRepository
from otelms.domain.repositories.category_availability import (
    CategoryAvailabilityRepository,
)

__all__ = [
    "ApiKeyRepository",
    "ApiKeyRoleRepository",
    "CategoryAvailabilityRepository",
    "CategoryRepository",
    "ChannelRateRepository",
    "DealerRepository",
    "GuestRepository",
    "HousekeepingStatusRepository",
    "HotelRepository",
    "PaymentMethodRepository",
    "PaymentRepository",
    "Permission",
    "PropertyServiceRepository",
    "ReservationChangeHistoryRepository",
    "ReservationNightRateRepository",
    "ReservationRepository",
    "RoleRepository",
    "RoomAvailabilityRepository",
    "RoomRepository",
    "ServiceRepository",
    "SyncLogRepository",
]

# Relaciones que ReservationResponse expone. La respuesta se arma en
# api.mappers.reservation_response leyendo solo atributos ya cargados, así que
# cualquier consulta de reservas que se vaya a serializar necesita esto: sin las
# relaciones precargadas, leerlas dispara MissingGreenlet en sesión async.
RESERVATION_DETAIL_OPTIONS = (
    selectinload(Reservation.guest),
    selectinload(Reservation.room).selectinload(Room.category),
    selectinload(Reservation.services),
    selectinload(Reservation.payments),
    selectinload(Reservation.night_rates),
    selectinload(Reservation.change_history),
)


class HotelRepository(BaseRepository[Hotel]):
    """Repositorio para operaciones de Hotel."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Hotel)

    async def get_by_id_with_relations(self, hotel_id: str) -> Hotel | None:
        """Obtiene hotel con relaciones cargadas."""
        stmt = (
            select(Hotel)
            .options(
                selectinload(Hotel.categories).selectinload(Category.rooms),
                selectinload(Hotel.rooms),
            )
            .where(Hotel.id == hotel_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_active(self) -> Sequence[Hotel]:
        """Obtiene todos los hoteles activos."""
        stmt = select(Hotel).where(Hotel.is_active).order_by(Hotel.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_username(self, username: str) -> Hotel | None:
        """Obtiene hotel por username."""
        stmt = select(Hotel).where(Hotel.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_last_sync(self, hotel_id: str) -> None:
        """Actualiza timestamp de última sincronización."""
        stmt = (
            Hotel.__table__.update()  # type: ignore[attr-defined]  # Table.update existe en SQLAlchemy (stub incompleto)
            .where(Hotel.id == hotel_id)
            .values(last_sync_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def get_active_with_config(self) -> Sequence[Hotel]:
        """Obtiene hoteles activos con configuración de scraper."""
        stmt = select(Hotel).where(Hotel.is_active).order_by(Hotel.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id_with_config(self, hotel_id: str) -> Hotel | None:
        """Obtiene hotel con configuración completa."""
        stmt = select(Hotel).where(Hotel.id == hotel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, id: str, **kwargs: Any) -> tuple[Hotel, bool]:  # type: ignore[override]  # especialización: devuelve (entity, is_new) vs ModelType del base
        """Insert or update (upsert) por ID. Retorna (entity, is_new)."""
        existing = await self.get_by_id(id)
        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False
        else:
            kwargs["id"] = id
            new_hotel = await self.create(**kwargs)
            return new_hotel, True


class CategoryRepository(BaseRepository):
    """Repositorio para categorías."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Category)

    async def get_by_hotel(self, hotel_id: str) -> Sequence:
        """Obtiene categorías de un hotel."""
        stmt = (
            select(Category)
            .where(Category.hotel_id == hotel_id)
            .order_by(Category.sort_order, Category.name)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_with_rooms(self, hotel_id: str) -> Sequence:
        """Obtiene categorías con sus habitaciones."""
        stmt = (
            select(Category)
            .options(selectinload(Category.rooms))
            .where(Category.hotel_id == hotel_id)
            .order_by(Category.sort_order, Category.name)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalars().all()

    async def get_by_id_with_rooms(self, hotel_id: str, category_id: str) -> Category | None:
        """Obtiene una categoría por ID (dentro del hotel) con sus habitaciones."""
        stmt = (
            select(Category)
            .options(selectinload(Category.rooms))
            .where(Category.hotel_id == hotel_id, Category.id == category_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def upsert_with_rooms(self, hotel_id: str, cat_data: dict) -> tuple:
        """Upsert categoría con sus habitaciones."""
        cat_id = cat_data.get("id")
        if not cat_id:
            raise ValueError("Category ID required")

        existing = await self.get_by_id(cat_id)
        if existing:
            existing.name = cat_data.get("name", existing.name)
            existing.hotel_id = hotel_id
            await self.session.flush()
            return existing, False
        else:
            cat = Category(
                id=cat_id,
                hotel_id=hotel_id,
                name=cat_data.get("name", ""),
            )
            self.session.add(cat)
            await self.session.flush()
            return cat, True


class RoomRepository(BaseRepository):
    """Repositorio para habitaciones."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Room)

    async def get_by_hotel(self, hotel_id: str, active_only: bool = True) -> Sequence:
        """Obtiene habitaciones de un hotel."""
        stmt = select(Room).where(Room.hotel_id == hotel_id)
        if active_only:
            stmt = stmt.where(Room.is_active)
        stmt = stmt.order_by(Room.floor, Room.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_category(self, category_id: str) -> Sequence:
        """Obtiene habitaciones de una categoría."""
        stmt = (
            select(Room)
            .where(Room.category_id == category_id)
            .order_by(Room.floor, Room.name)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_available_for_dates(
        self, hotel_id: str, check_in: str, check_out: str
    ) -> Sequence:
        """Obtiene habitaciones disponibles para un rango de fechas (simplificado)."""
        # Nota: La disponibilidad real requiere consultar reservas overlapping
        # Esta es una versión básica; para producción usar query más complejo


        check_in_dt = datetime.fromisoformat(check_in.replace("Z", "+00:00"))
        check_out_dt = datetime.fromisoformat(check_out.replace("Z", "+00:00"))

        # Subquery de habitaciones con reservas overlapping
        occupied_room_ids = select(Reservation.room_id).where(
            Reservation.hotel_id == hotel_id,
            Reservation.status.in_([1, 2]),  # Reserva o Check-in
            Reservation.check_in < check_out_dt,
            Reservation.check_out > check_in_dt,
        )

        stmt = (
            select(Room)
            .options(selectinload(Room.category))
            .where(
                Room.hotel_id == hotel_id,
                Room.is_active,
                Room.id.not_in(occupied_room_ids),
            )
            .order_by(Room.floor, Room.name)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_hotel_with_category(
        self, hotel_id: str, active_only: bool = True
    ) -> Sequence:
        """Obtiene habitaciones de un hotel con su categoría precargada."""
        stmt = select(Room).options(selectinload(Room.category)).where(Room.hotel_id == hotel_id)
        if active_only:
            stmt = stmt.where(Room.is_active)
        stmt = stmt.order_by(Room.floor, Room.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_occupied_for_date(
        self, hotel_id: str, target_date: date | str | None = None
    ) -> Sequence:
        """Obtiene reservas que ocupan noche en una fecha (noches vendidas).

        Una habitación se considera ocupada la noche D si tiene reserva
        vigente (status 1 o 2) con date(check_in) <= D < date(check_out).
        El día de salida NO cuenta como ocupada (el huésped sale; ver
        get_checkouts_for_date). La vista calendario de OtelMS no distingue
        check-in, por eso se incluyen statuses 1 y 2.
        Retorna reservas con room/categoría/guest precargados,
        ordenadas por check_out (próximas salidas primero).
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        stmt = (
            select(Reservation)
            .options(
                selectinload(Reservation.room).selectinload(Room.category),
                selectinload(Reservation.guest),
            )
            .where(
                Reservation.hotel_id == hotel_id,
                Reservation.status.in_([1, 2]),  # Reserva o Check-in vigente
                func.date(Reservation.check_in) <= target_date,
                func.date(Reservation.check_out) > target_date,
            )
            .order_by(Reservation.check_out)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def upsert(self, hotel_id: str, room_data: dict) -> tuple:  # type: ignore[override]  # firma especializada: (hotel_id, room_data) vs (id, **kwargs) del base
        """Upsert habitación."""
        room_id = room_data.get("id")
        if not room_id:
            raise ValueError("Room ID required")

        existing = await self.get_by_id(room_id)
        if existing:
            existing.name = room_data.get("name", existing.name)
            existing.hotel_id = hotel_id
            existing.category_id = room_data.get("category_id")
            await self.session.flush()
            return existing, False
        else:
            room = Room(
                id=room_id,
                hotel_id=hotel_id,
                name=room_data.get("name", ""),
                category_id=room_data.get("category_id"),
            )
            self.session.add(room)
            await self.session.flush()
            return room, True


class GuestRepository(BaseRepository):
    """Repositorio para huéspedes."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Guest)

    async def get_by_hotel(self, hotel_id: str, limit: int = 100, offset: int = 0) -> Sequence:
        """Obtiene huéspedes de un hotel."""
        stmt = (
            select(Guest)
            .where(Guest.hotel_id == hotel_id)
            .order_by(Guest.last_name, Guest.first_name)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def search(
        self,
        hotel_id: str,
        query: str,
        limit: int = 50,
    ) -> Sequence:
        """Busca huéspedes por nombre, email, documento."""

        stmt = (
            select(Guest)
            .where(
                Guest.hotel_id == hotel_id,
                or_(
                    Guest.first_name.ilike(f"%{query}%"),
                    Guest.last_name.ilike(f"%{query}%"),
                    Guest.email.ilike(f"%{query}%"),
                    Guest.document_number.ilike(f"%{query}%"),
                ),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_document(
        self, hotel_id: str, document_type: str, document_number: str
    ) -> Guest | None:
        """Obtiene huésped por documento."""
        stmt = select(Guest).where(
            Guest.hotel_id == hotel_id,
            Guest.document_type == document_type,
            Guest.document_number == document_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_by_name(self, hotel_id: str, name: str) -> tuple:
        """Obtiene o crea huésped por nombre (básico)."""
        parts = name.split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        stmt = select(Guest).where(
            Guest.hotel_id == hotel_id,
            Guest.first_name == first_name,
            Guest.last_name == last_name,
        )
        result = await self.session.execute(stmt)
        guest = result.scalar_one_or_none()

        if guest:
            return guest, False

        guest_id = f"guest_{hashlib.sha256(name.encode()).hexdigest()[:12]}"
        guest = Guest(
            id=guest_id,
            hotel_id=hotel_id,
            first_name=first_name,
            last_name=last_name,
        )
        self.session.add(guest)
        await self.session.flush()
        return guest, True

    async def upsert_from_scraper(self, hotel_id: str, guest_data: dict) -> tuple:
        """Upsert huésped desde datos del scraper."""
        guest_id = guest_data.get("id")
        if not guest_id:
            # Generar ID basado en documento o nombre
            doc = guest_data.get("document_number") or ""
            if doc:
                guest_id = f"guest_{doc}"
            else:
                name = guest_data.get("name") or guest_data.get("first_name", "")
                guest_id = f"guest_{hash(name)}"

        existing = await self.get_by_id(guest_id)
        if existing:
            # Actualizar campos
            for key, value in guest_data.items():
                if hasattr(existing, key) and key not in ["id", "hotel_id", "created_at"]:
                    setattr(existing, key, value)
            await self.session.flush()
            return existing, False
        else:
            guest_data["id"] = guest_id
            guest_data["hotel_id"] = hotel_id
            guest = Guest(**guest_data)
            self.session.add(guest)
            await self.session.flush()
            return guest, True


class ReservationRepository(BaseRepository):
    """Repositorio para reservas."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Reservation)

    async def get_by_hotel(
        self,
        hotel_id: str,
        *,
        status: int | None = None,
        check_in_from: datetime | None = None,
        check_in_to: datetime | None = None,
        check_out_from: datetime | None = None,
        check_out_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "check_in",
    ) -> Sequence:
        """Obtiene reservas de un hotel con filtros y relaciones precargadas."""

        stmt = select(Reservation).options(*RESERVATION_DETAIL_OPTIONS)
        stmt = stmt.where(Reservation.hotel_id == hotel_id)

        if status is not None:
            stmt = stmt.where(Reservation.status == status)

        if check_in_from:
            if isinstance(check_in_from, str):
                check_in_from = datetime.fromisoformat(check_in_from.replace("Z", "+00:00"))
            stmt = stmt.where(Reservation.check_in >= check_in_from)

        if check_in_to:
            if isinstance(check_in_to, str):
                check_in_to = datetime.fromisoformat(check_in_to.replace("Z", "+00:00"))
            stmt = stmt.where(Reservation.check_in <= check_in_to)

        if check_out_from:
            if isinstance(check_out_from, str):
                check_out_from = datetime.fromisoformat(check_out_from.replace("Z", "+00:00"))
            stmt = stmt.where(Reservation.check_out >= check_out_from)

        if check_out_to:
            if isinstance(check_out_to, str):
                check_out_to = datetime.fromisoformat(check_out_to.replace("Z", "+00:00"))
            stmt = stmt.where(Reservation.check_out <= check_out_to)

        stmt = stmt.order_by(getattr(Reservation, order_by).desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_with_details(self, hotel_id: str, reservation_id: str) -> Reservation | None:
        """Obtiene reserva con todas las relaciones cargadas."""
        stmt = (
            select(Reservation)
            .options(*RESERVATION_DETAIL_OPTIONS)
            .where(Reservation.hotel_id == hotel_id, Reservation.id == reservation_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def count_by_hotel(
        self,
        hotel_id: str,
        status: int | None = None,
    ) -> int:
        """Cuenta reservas de un hotel."""

        stmt = select(func.count()).select_from(Reservation).where(Reservation.hotel_id == hotel_id)
        if status is not None:
            stmt = stmt.where(Reservation.status == status)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_checkins_for_date(
        self, hotel_id: str, target_date: date | str | None = None
    ) -> Sequence:
        """Obtiene llegadas (status == 1) con check_in en una fecha (default hoy).

        Retorna reservas con room/categoría/guest precargados.
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        stmt = (
            select(Reservation)
            .options(
                selectinload(Reservation.room).selectinload(Room.category),
                selectinload(Reservation.guest),
            )
            .where(
                Reservation.hotel_id == hotel_id,
                Reservation.status == 1,  # Reserva
                func.date(Reservation.check_in) == target_date,
            )
            .order_by(Reservation.check_in)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_checkouts_for_date(
        self, hotel_id: str, target_date: date | str | None = None
    ) -> Sequence:
        """Obtiene salidas programadas (status 1 o 2) con check_out en una fecha.

        La vista calendario no distingue check-in: las salidas se derivan por
        fecha de salida de reservas vigentes. Retorna reservas con
        room/categoría/guest precargados.
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        stmt = (
            select(Reservation)
            .options(
                selectinload(Reservation.room).selectinload(Room.category),
                selectinload(Reservation.guest),
            )
            .where(
                Reservation.hotel_id == hotel_id,
                Reservation.status.in_([1, 2]),  # vigentes (la vista no distingue check-in)
                func.date(Reservation.check_out) == target_date,
            )
            .order_by(Reservation.check_out)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_today_checkins(self, hotel_id: str) -> Sequence:
        """Obtiene check-ins de hoy (atajo de get_checkins_for_date)."""
        return await self.get_checkins_for_date(hotel_id)

    async def get_today_checkouts(self, hotel_id: str) -> Sequence:
        """Obtiene check-outs de hoy (atajo de get_checkouts_for_date)."""
        return await self.get_checkouts_for_date(hotel_id)

    async def get_pending_charges(
        self,
        hotel_id: str,
        *,
        only_pending: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Calcula saldos pendientes por reserva.

        Fórmula: sum(services.total) - sum(payments.amount).
        Retorna una lista de dicts con reservation_id, total_charges,
        total_paid, pending, guest_name, room_id, check_in, check_out, nights.

        Si `only_pending=True`, filtra reservas con pending != 0.
        """
        from sqlalchemy import func as _func

        stmt = (
            select(
                Reservation.id.label("reservation_id"),
                Guest.first_name.label("first_name"),
                Guest.last_name.label("last_name"),
                Room.id.label("room_id"),
                Room.name.label("room_name"),
                Reservation.check_in,
                Reservation.check_out,
                Reservation.status,
                _func.coalesce(_func.sum(Service.total), 0).label("total_charges"),
                _func.coalesce(_func.sum(Payment.amount), 0).label("total_paid"),
            )
            .outerjoin(Service, Service.reservation_id == Reservation.id)
            .outerjoin(Payment, Payment.reservation_id == Reservation.id)
            .outerjoin(Guest, Guest.id == Reservation.guest_id)
            .outerjoin(Room, Room.id == Reservation.room_id)
            .where(Reservation.hotel_id == hotel_id)
            .group_by(
                Reservation.id,
                Guest.first_name,
                Guest.last_name,
                Room.id,
                Room.name,
                Reservation.check_in,
                Reservation.check_out,
                Reservation.status,
            )
        )

        if only_pending:
            stmt = stmt.having(
                _func.coalesce(_func.sum(Service.total), 0)
                != _func.coalesce(_func.sum(Payment.amount), 0)
            )

        stmt = stmt.order_by(_func.abs(
            _func.coalesce(_func.sum(Service.total), 0)
            - _func.coalesce(_func.sum(Payment.amount), 0)
        ).desc()).limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        rows = result.all()

        items = []
        for row in rows:
            check_in = row.check_in
            check_out = row.check_out
            nights = max((check_out.date() - check_in.date()).days, 0) if check_in and check_out else 0
            total_charges = float(row.total_charges or 0)
            total_paid = float(row.total_paid or 0)
            pending = round(total_charges - total_paid, 2)

            first = (row.first_name or "").strip()
            last = (row.last_name or "").strip()
            guest_name = " ".join(p for p in (first, last) if p) or None

            items.append({
                "reservation_id": row.reservation_id,
                "guest_name": guest_name,
                "room_id": row.room_id,
                "room_name": row.room_name,
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                "total_charges": total_charges,
                "total_paid": total_paid,
                "pending": pending,
                "currency": "USD",
                "status": row.status,
            })

        return items

    async def upsert_from_scraper(self, hotel_id: str, data: dict) -> tuple:
        """
        Upsert desde datos del scraper.
        Retorna (objeto, creado: bool, actualizado: bool).
        """

        reservation_id = data.get("id") or data.get("reservation_number")
        if not reservation_id:
            raise ValueError("Reservation ID es requerido")

        # Normalizar fechas ISO a datetime (SQLite no acepta strings)
        for field in ("check_in", "check_out", "otelms_created_at", "otelms_updated_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])

        # Calcular hash para detectar cambios
        relevant_fields = {
            k: v for k, v in data.items()
            if k not in ["id", "last_synced_at", "sync_hash", "created_at", "updated_at"]
        }
        sync_hash = hashlib.sha256(json.dumps(relevant_fields, sort_keys=True, default=str).encode()).hexdigest()[:64]

        existing = await self.get_by_id(reservation_id)
        if existing:
            if existing.sync_hash == sync_hash:
                # Sin cambios
                return existing, False, False

            # Actualizar
            for key, value in data.items():
                if hasattr(existing, key) and key not in ["id", "created_at"]:
                    setattr(existing, key, value)
            existing.sync_hash = sync_hash
            existing.last_synced_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False, True
        else:
            # Crear nuevo
            data["id"] = reservation_id
            data["hotel_id"] = hotel_id
            data["sync_hash"] = sync_hash
            data["last_synced_at"] = datetime.now(UTC)
            obj = await self.create(**data)
            return obj, True, False


class ServiceRepository(BaseRepository):
    """Repositorio para servicios."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Service)

    async def get_by_reservation(self, reservation_id: str) -> Sequence:
        """Obtiene servicios de una reserva."""
        stmt = (
            select(Service)
            .where(Service.reservation_id == reservation_id)
            .order_by(Service.date)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def bulk_upsert(self, reservation_id: str, services: list[dict]) -> int:
        """Bulk upsert de servicios para una reserva."""

        if not services:
            return 0

        # Primero eliminar los existentes para este reservation_id (estrategia simple)
        await self.session.execute(
            delete(Service).where(Service.reservation_id == reservation_id)
        )

        # Insertar nuevos
        for svc in services:
            svc["reservation_id"] = reservation_id
            if isinstance(svc.get("date"), str):
                svc["date"] = datetime.fromisoformat(svc["date"])
            obj = Service(**svc)
            self.session.add(obj)

        await self.session.flush()
        return len(services)


class PaymentRepository(BaseRepository):
    """Repositorio para pagos."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Payment)

    async def get_by_reservation(self, reservation_id: str) -> Sequence:
        """Obtiene pagos de una reserva."""
        stmt = (
            select(Payment)
            .where(Payment.reservation_id == reservation_id)
            .order_by(Payment.date)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_total_paid(self, reservation_id: str) -> float:
        """Obtiene total pagado de una reserva."""

        stmt = select(func.sum(Payment.amount)).where(Payment.reservation_id == reservation_id)
        result = await self.session.execute(stmt)
        return float(result.scalar() or 0)

    async def bulk_upsert(self, reservation_id: str, payments: list[dict]) -> int:
        """Bulk upsert de pagos para una reserva."""

        if not payments:
            return 0

        await self.session.execute(
            delete(Payment).where(Payment.reservation_id == reservation_id)
        )

        for pmt in payments:
            pmt["reservation_id"] = reservation_id
            if isinstance(pmt.get("date"), str):
                pmt["date"] = datetime.fromisoformat(pmt["date"])
            obj = Payment(**pmt)
            self.session.add(obj)

        await self.session.flush()
        return len(payments)


class SyncLogRepository(BaseRepository):
    """Repositorio para logs de sincronización."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SyncLog)

    async def get_by_hotel(
        self,
        hotel_id: str,
        sync_type: str | None = None,
        limit: int = 50,
    ) -> Sequence:
        """Obtiene logs de sincronización de un hotel."""
        stmt = select(SyncLog).where(SyncLog.hotel_id == hotel_id)
        if sync_type:
            stmt = stmt.where(SyncLog.sync_type == sync_type)
        stmt = stmt.order_by(SyncLog.started_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_log(
        self,
        hotel_id: str,
        sync_type: str,
    ) -> "SyncLog":
        """Crea un log de sincronización iniciado."""
        log = SyncLog(
            hotel_id=hotel_id,
            sync_type=sync_type,
            status="started",
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def complete_log(
        self,
        log_id: int,
        status: str,
        records_processed: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        """Completa un log de sincronización."""
        log = await self.get_by_id(log_id)  # type: ignore[arg-type]  # SyncLog.id es int (auto-increment), el base asume str
        if log:
            log.status = status
            log.completed_at = datetime.now(UTC)
            # SQLite devuelve started_at sin tzinfo → hacer aware antes de restar
            started = log.started_at.replace(tzinfo=UTC) if log.started_at and log.started_at.tzinfo is None else log.started_at
            log.duration_ms = int((log.completed_at - started).total_seconds() * 1000) if started else 0
            log.records_processed = records_processed
            log.records_created = records_created
            log.records_updated = records_updated
            log.errors = json.dumps(errors) if errors else None
            log.error_count = len(errors) if errors else 0
            await self.session.flush()


class ApiKeyRepository(BaseRepository):
    """Repositorio para API Keys."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ApiKey)

    async def get_by_key_hash(self, key_hash: str) -> Optional["ApiKey"]:
        """Obtiene API Key por hash."""
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_last_used(self, key_id: str) -> None:
        """Actualiza timestamp de último uso."""

        stmt = (
            ApiKey.__table__.update()  # type: ignore[attr-defined]  # Table.update existe en SQLAlchemy (stub incompleto)
            .where(ApiKey.id == key_id)
            .values(last_used_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)


class DealerRepository(BaseRepository[Dealer]):
    """Repositorio para canales de venta / dealers."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Dealer)

    async def get_by_hotel(self, hotel_id: str, active_only: bool = True) -> Sequence[Dealer]:
        stmt = select(Dealer).where(Dealer.hotel_id == hotel_id)
        if active_only:
            stmt = stmt.where(Dealer.is_active)
        stmt = stmt.order_by(Dealer.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PaymentMethodRepository(BaseRepository[PaymentMethod]):
    """Repositorio para métodos de pago."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, PaymentMethod)

    async def get_by_hotel(self, hotel_id: str, active_only: bool = True) -> Sequence[PaymentMethod]:
        stmt = select(PaymentMethod).where(PaymentMethod.hotel_id == hotel_id)
        if active_only:
            stmt = stmt.where(PaymentMethod.is_active)
        stmt = stmt.order_by(PaymentMethod.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PropertyServiceRepository(BaseRepository[PropertyService]):
    """Repositorio para servicios de la propiedad/hotel."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, PropertyService)

    async def get_by_hotel(self, hotel_id: str, active_only: bool = True) -> Sequence[PropertyService]:
        stmt = select(PropertyService).where(PropertyService.hotel_id == hotel_id)
        if active_only:
            stmt = stmt.where(PropertyService.is_active)
        stmt = stmt.order_by(PropertyService.name)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ReservationNightRateRepository(BaseRepository[ReservationNightRate]):
    """Repositorio para tarifas por noche de una reserva."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ReservationNightRate)

    async def get_by_reservation(self, reservation_id: str) -> Sequence[ReservationNightRate]:
        stmt = (
            select(ReservationNightRate)
            .where(ReservationNightRate.reservation_id == reservation_id)
            .order_by(ReservationNightRate.date)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def bulk_upsert(self, reservation_id: str, rates: list[dict]) -> int:
        if not rates:
            return 0
        await self.session.execute(
            delete(ReservationNightRate).where(ReservationNightRate.reservation_id == reservation_id)
        )
        for idx, r in enumerate(rates):
            r["reservation_id"] = reservation_id
            if not r.get("id"):
                r["id"] = f"{reservation_id}-rate-{r.get('date')}-{idx}"
            if isinstance(r.get("date"), str):
                r["date"] = date.fromisoformat(r["date"])
            self.session.add(ReservationNightRate(**r))
        await self.session.flush()
        return len(rates)


class ReservationChangeHistoryRepository(BaseRepository[ReservationChangeHistory]):
    """Repositorio para el historial de cambios y auditoría de una reserva."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ReservationChangeHistory)

    async def get_by_reservation(self, reservation_id: str) -> Sequence[ReservationChangeHistory]:
        stmt = (
            select(ReservationChangeHistory)
            .where(ReservationChangeHistory.reservation_id == reservation_id)
            .order_by(ReservationChangeHistory.date.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def bulk_upsert(self, reservation_id: str, history_items: list[dict]) -> int:
        if not history_items:
            return 0
        await self.session.execute(
            delete(ReservationChangeHistory).where(ReservationChangeHistory.reservation_id == reservation_id)
        )
        for idx, h in enumerate(history_items):
            h["reservation_id"] = reservation_id
            if not h.get("id"):
                h["id"] = f"{reservation_id}-hist-{idx}"
            if isinstance(h.get("date"), str):
                try:
                    h["date"] = datetime.fromisoformat(h["date"])
                except Exception:
                    h["date"] = None
            self.session.add(ReservationChangeHistory(**h))
        await self.session.flush()
        return len(history_items)


from otelms.domain.repositories.rh_repos import (
    ApiKeyRoleRepository,
    HousekeepingStatusRepository,
    RoleRepository,
    RoomAvailabilityRepository,
)
from otelms.domain.repositories.channel_rate_repos import ChannelRateRepository
