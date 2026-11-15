"""
Repositories for Role, ApiKeyRole, HousekeepingStatus, and RoomAvailability entities.
"""
import json
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import ApiKeyRole, HousekeepingStatus, Role, RoomAvailability
from otelms.domain.repositories.base import BaseRepository


class RoleRepository(BaseRepository):
    """Repositorio para Roles."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Role)

    async def get_permissions(self, role_id: str) -> list[str]:
        """Obtiene los permisos de un rol como lista de strings."""
        role = await self.get_by_id(role_id)
        if not role:
            return []
        try:
            perms = role.permissions
            if isinstance(perms, str):
                return json.loads(perms) if perms else []
            return list(perms) if perms else []
        except (json.JSONDecodeError, TypeError):
            return []


class ApiKeyRoleRepository(BaseRepository):
    """Repositorio para relacion API Key - Role."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ApiKeyRole)

    async def get_roles_for_key(self, api_key_id: str) -> list[Role]:
        """Obtiene los roles asignados a una API Key."""
        stmt = (
            select(Role)
            .join(ApiKeyRole, Role.id == ApiKeyRole.role_id)
            .where(ApiKeyRole.api_key_id == api_key_id, Role.is_active)
            .order_by(Role.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class HousekeepingStatusRepository(BaseRepository):
    """Repositorio para estado de limpieza de habitaciones."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, HousekeepingStatus)

    async def get_cleaned_room_ids_for_date(
        self, hotel_id: str, target_date: date
    ) -> set[str]:
        """Obtiene los room_ids ya marcadas como limpias para una fecha."""
        from sqlalchemy import select as _q
        stmt = (
            _q(HousekeepingStatus.room_id)
            .where(
                HousekeepingStatus.hotel_id == hotel_id,
                HousekeepingStatus.date == target_date,
                HousekeepingStatus.status == 2,
            )
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def get_notes_map_for_date(self, hotel_id: str, target_date: date) -> dict[str, str]:
        """Retorna {room_id: notes} para habitaciones con observaciones en esa fecha."""
        from sqlalchemy import select as _q
        stmt = (
            _q(HousekeepingStatus.room_id, HousekeepingStatus.notes)
            .where(
                HousekeepingStatus.hotel_id == hotel_id,
                HousekeepingStatus.date == target_date,
                HousekeepingStatus.notes.is_not(None),
            )
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all() if row[1]}

    async def upsert(
        self,
        hotel_id: str,
        room_id: str,
        target_date: date,
        status: int,
        updated_by: str | None = None,
        notes: str | None = None,
    ) -> HousekeepingStatus:
        """Crea o actualiza el estado de limpieza de una habitacion."""
        from sqlalchemy import select as _q
        stmt = (
            _q(HousekeepingStatus)
            .where(
                HousekeepingStatus.hotel_id == hotel_id,
                HousekeepingStatus.room_id == room_id,
                HousekeepingStatus.date == target_date,
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.status = status
            existing.updated_by = updated_by
            if notes is not None:
                existing.notes = notes
            existing.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        obj = HousekeepingStatus(
            id=str(uuid.uuid4()),
            hotel_id=hotel_id,
            room_id=room_id,
            date=target_date,
            status=status,
            notes=notes,
            updated_by=updated_by,
        )
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def reset_date(self, hotel_id: str, target_date: date) -> int:
        """Reinicia todos los estados de limpieza de una fecha a pending (0)."""
        stmt = (
            HousekeepingStatus.__table__.update()
            .where(
                HousekeepingStatus.hotel_id == hotel_id,
                HousekeepingStatus.date == target_date,
            )
            .values(status=0, updated_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0


class RoomAvailabilityRepository(BaseRepository):
    """Repositorio para bloqueos/desbloqueos de disponibilidad de habitaciones."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, RoomAvailability)

    async def get_blocked_room_ids_for_date(
        self, hotel_id: str, target_date: date, room_ids: list[str] | None = None
    ) -> tuple[set[str], bool]:
        """Obtiene los room_ids bloqueados (is_blocked=True) para una fecha.

        Incluye bloqueos globales (room_id = NULL) que aplican a todas las habitaciones
        del hotel, y bloqueos específicos por room_id.
        
        Returns:
            Tuple of (blocked_room_ids_set, has_global_block)
        """
        from sqlalchemy import select as _q

        # Bloqueos específicos por room_id
        stmt_specific = (
            _q(RoomAvailability.room_id)
            .where(
                RoomAvailability.hotel_id == hotel_id,
                RoomAvailability.room_id.is_not(None),
                RoomAvailability.is_blocked == True,
                RoomAvailability.start_date <= target_date,
                RoomAvailability.end_date >= target_date,
            )
        )
        if room_ids:
            stmt_specific = stmt_specific.where(RoomAvailability.room_id.in_(room_ids))

        result_specific = await self.session.execute(stmt_specific)
        blocked_specific = {row[0] for row in result_specific.all()}

        # Bloqueos globales (room_id = NULL) - aplican a todas las habitaciones del hotel
        stmt_global = (
            _q(RoomAvailability.room_id)
            .where(
                RoomAvailability.hotel_id == hotel_id,
                RoomAvailability.room_id.is_(None),
                RoomAvailability.is_blocked == True,
                RoomAvailability.start_date <= target_date,
                RoomAvailability.end_date >= target_date,
            )
        )
        result_global = await self.session.execute(stmt_global)
        # Si hay bloqueo global, devolver todas las habitaciones (manejado en el endpoint)
        has_global_block = result_global.scalar_one_or_none() is not None

        return blocked_specific, has_global_block

    async def get_all_for_hotel_date(
        self, hotel_id: str, target_date: date
    ) -> list[RoomAvailability]:
        """Obtiene todos los registros de disponibilidad (bloqueos y desbloqueos) para un hotel/fecha."""
        from sqlalchemy import select as _q
        stmt = (
            _q(RoomAvailability)
            .where(
                RoomAvailability.hotel_id == hotel_id,
                RoomAvailability.start_date <= target_date,
                RoomAvailability.end_date >= target_date,
            )
            .order_by(RoomAvailability.room_id.is_(None).desc(), RoomAvailability.room_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        hotel_id: str,
        start_date: date,
        end_date: date,
        is_blocked: bool,
        room_id: str | None = None,
        reason: str | None = None,
    ) -> RoomAvailability:
        """Crea o actualiza un registro de disponibilidad/bloqueo."""
        from sqlalchemy import select as _q
        stmt = (
            _q(RoomAvailability)
            .where(
                RoomAvailability.hotel_id == hotel_id,
                RoomAvailability.room_id == room_id,
                RoomAvailability.start_date == start_date,
                RoomAvailability.end_date == end_date,
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.is_blocked = is_blocked
            existing.reason = reason
            existing.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        obj = RoomAvailability(
            id=str(uuid.uuid4()),
            hotel_id=hotel_id,
            room_id=room_id,
            start_date=start_date,
            end_date=end_date,
            is_blocked=is_blocked,
            reason=reason,
        )
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj
