"""
Configuración de base de datos y sesión.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from otelms.config.settings import settings
from otelms.domain.entities import Base


class Database:
    """Gestor de conexión a base de datos."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or settings.database_url
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            is_sqlite = "sqlite" in self.database_url

            engine_kwargs = {
                "echo": settings.app_debug,
            }

            if is_sqlite:
                engine_kwargs.update({
                    "poolclass": NullPool,
                    "connect_args": {"check_same_thread": False},
                })
            else:
                engine_kwargs.update({
                    "pool_size": settings.db_pool_size,
                    "max_overflow": settings.db_max_overflow,
                    "pool_timeout": settings.db_pool_timeout,
                    "pool_recycle": settings.db_pool_recycle,
                })

            self._engine = create_async_engine(self.database_url, **engine_kwargs)

        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._session_factory

    async def create_all(self) -> None:
        """Crea todas las tablas (solo para desarrollo/testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        """Elimina todas las tablas (solo para testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provee una sesión transaccional."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def close(self) -> None:
        """Cierra el engine y conexiones."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Instancia global
db = Database()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para FastAPI - obtiene sesión de BD."""
    async with db.session() as session:
        yield session


async def init_db() -> None:
    """Inicializa la base de datos (crea tablas si no existen)."""
    await db.create_all()


async def close_db() -> None:
    """Cierra conexiones de BD."""
    await db.close()
