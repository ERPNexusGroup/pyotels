"""
Repositorio base con operaciones CRUD comunes.
"""
from typing import Generic, TypeVar, Sequence

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Repositorio base con operaciones CRUD genéricas."""

    def __init__(self, session: AsyncSession, model: type[ModelType]):
        self.session = session
        self.model = model

    async def create(self, **kwargs) -> ModelType:
        """Crea una nueva entidad."""
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_by_id(self, id: str) -> ModelType | None:
        """Obtiene entidad por ID."""
        stmt = select(self.model).where(self.model.id == id)
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

    async def update(self, id: str, **kwargs) -> ModelType | None:
        """Actualiza entidad por ID."""
        stmt = (
            update(self.model)
            .where(self.model.id == id)
            .values(**kwargs)
            .returning(self.model)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, id: str) -> bool:
        """Elimina entidad por ID."""
        stmt = delete(self.model).where(self.model.id == id)
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def exists(self, id: str) -> bool:
        """Verifica si existe entidad por ID."""
        stmt = select(func.count()).select_from(self.model).where(self.model.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    async def upsert(self, id: str, **kwargs) -> ModelType:
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