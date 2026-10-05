"""
Repositorio de disponibilidad por categoría y fecha.

Vive en su propio módulo (y no dentro de `CategoryRepository`) porque la
disponibilidad no cuelga de una categoría sino de (categoría, fecha): es la fila
de resumen del calendario, no un atributo de la categoría.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import CategoryAvailability
from otelms.domain.repositories.base import BaseRepository


class CategoryAvailabilityRepository(BaseRepository[CategoryAvailability]):
    """Disponibilidad que publica OtelMS por categoría y día."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, CategoryAvailability)

    async def replace(self, hotel_id: str, rows: list[dict[str, Any]]) -> int:
        """Reemplaza la disponibilidad de las categorías presentes en `rows`.

        Se borra por (hotel_id, categoría) y se reinserta el rango completo que
        vino del calendario: una ventana de sync deja de valer en cuanto el
        portal cambia un día, y las filas que ya no vengan se quedarían
        congeladas si solo se hiciera upsert.
        """
        if not rows:
            return 0

        category_ids = {row["category_id"] for row in rows}
        await self.session.execute(
            delete(CategoryAvailability).where(
                CategoryAvailability.hotel_id == hotel_id,
                CategoryAvailability.category_id.in_(category_ids),
            )
        )

        for row in rows:
            self.session.add(CategoryAvailability(
                id=f"{row['category_id']}-{row['date']}",
                hotel_id=hotel_id,
                category_id=row["category_id"],
                date=date.fromisoformat(row["date"]),
                available=row["available"],
            ))

        await self.session.flush()
        return len(rows)

    async def get_range(
        self,
        hotel_id: str,
        date_from: date,
        date_to: date,
        category_id: str | None = None,
    ) -> Sequence[CategoryAvailability]:
        """Disponibilidad de un rango de fechas, opcionalmente de una categoría."""
        stmt = select(CategoryAvailability)

        if hotel_id:
            stmt = stmt.where(CategoryAvailability.hotel_id == hotel_id)
        if date_from:
            stmt = stmt.where(CategoryAvailability.date >= date_from)
        if date_to:
            stmt = stmt.where(CategoryAvailability.date <= date_to)
        if category_id:
            stmt = stmt.where(CategoryAvailability.category_id == category_id)

        stmt = stmt.order_by(
            CategoryAvailability.date, CategoryAvailability.category_id
        )

        result = await self.session.execute(stmt)
        return result.scalars().all()
