"""
Repository for ChannelRate entity (OTA / direct channel rates).
"""
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select as _q
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.domain.entities import ChannelRate
from otelms.domain.repositories.base import BaseRepository


class ChannelRateRepository(BaseRepository):
    """Repositorio para tarifas por canal (OTA / directo)."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ChannelRate)

    async def get_by_hotel(
        self,
        hotel_id: str,
        *,
        category_id: str | None = None,
        channel: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ChannelRate]:
        """Lista tarifas de canal de un hotel con filtros optionales."""
        stmt = _q(ChannelRate).where(ChannelRate.hotel_id == hotel_id)
        if category_id:
            stmt = stmt.where(ChannelRate.category_id == category_id)
        if channel:
            stmt = stmt.where(ChannelRate.channel == channel)
        if date_from:
            stmt = stmt.where(ChannelRate.date >= date_from)
        if date_to:
            stmt = stmt.where(ChannelRate.date <= date_to)
        stmt = stmt.order_by(ChannelRate.date, ChannelRate.category_id).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_for_availability(
        self,
        hotel_id: str,
        category_id: str,
        date_from: date,
        date_to: date,
    ) -> list[dict]:
        """Obtiene tarifas de canal para una categoria en un rango de fechas."""
        stmt = (
            _q(
                ChannelRate.date,
                ChannelRate.channel,
                ChannelRate.rate_id,
                ChannelRate.price,
                ChannelRate.currency,
                ChannelRate.min_stay,
            )
            .where(
                ChannelRate.hotel_id == hotel_id,
                ChannelRate.category_id == category_id,
                ChannelRate.date >= date_from,
                ChannelRate.date <= date_to,
            )
            .order_by(ChannelRate.date, ChannelRate.channel)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {
                "date": r[0],
                "channel": r[1],
                "rate_id": r[2],
                "price": r[3],
                "currency": r[4],
                "min_stay": r[5],
            }
            for r in rows
        ]

    async def upsert_rate(
        self,
        hotel_id: str,
        category_id: str,
        rate_id: str,
        channel: str,
        target_date: date,
        price: Decimal,
        currency: str = "USD",
        min_stay: int | None = None,
    ) -> ChannelRate:
        """Inserta o actualiza una tarifa de canal."""
        existing = await self.session.execute(
            _q(ChannelRate).where(
                ChannelRate.hotel_id == hotel_id,
                ChannelRate.category_id == category_id,
                ChannelRate.rate_id == rate_id,
                ChannelRate.channel == channel,
                ChannelRate.date == target_date,
            )
        )
        rate = existing.scalar_one_or_none()
        if rate:
            rate.price = price
            rate.currency = currency
            rate.min_stay = min_stay
            await self.session.flush()
            await self.session.refresh(rate)
            return rate
        rate = ChannelRate(
            id=str(uuid.uuid4()),
            hotel_id=hotel_id,
            category_id=category_id,
            rate_id=rate_id,
            channel=channel,
            date=target_date,
            price=price,
            currency=currency,
            min_stay=min_stay,
        )
        self.session.add(rate)
        await self.session.flush()
        await self.session.refresh(rate)
        return rate
