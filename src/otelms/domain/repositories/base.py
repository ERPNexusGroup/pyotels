"""
Repositorio base con operaciones CRUD comunes.
"""
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository[ModelType: Base]:
    """Repositorio base con operaciones CRUD genéricas."""

    def __init__(self, session: AsyncSession, model: type[ModelType]):
        self.session = session
        self.model = model

    async def create(self, **kwargs: Any) -> ModelType:
        """Crea una nueva entidad."""
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_by_id(self, id: str) -> ModelType | None:
        """Obtiene entidad por ID."""
        # todos los modelos heredan .id de la declarative base
        stmt = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        order_by: str | None = None,
    ) -> Sequence[ModelType]:
        """Obtiene todas las entidades con paginación."""
        stmt = select(self.model).limit(limit).offset(offset)
        if order_by:
            stmt = stmt.order_by(getattr(self.model, order_by))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Cuenta total de entidades."""
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update(self, id: str, **kwargs: Any) -> ModelType | None:
        """Actualiza entidad por ID."""
        stmt = (
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(**kwargs)
            .returning(self.model)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, id: str) -> bool:
        """Elimina entidad por ID."""
        stmt = delete(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        # CursorResult.rowcount no está en el stub de Result
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]

    async def exists(self, id: str) -> bool:
        """Verifica si existe entidad por ID."""
        stmt = select(func.count()).select_from(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    async def upsert(self, id: str, **kwargs: Any) -> ModelType:
        """Insert or update (upsert) por ID."""
        existing = await self.get_by_id(id)
        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            kwargs["id"] = id
            return await self.create(**kwargs)
