"""Test E2E: sincronizar el calendario y comprobar que persiste la disponibilidad."""

import asyncio
from collections import Counter
from datetime import date

from otelms.config.settings import get_settings
from otelms.domain.repositories import CategoryAvailabilityRepository
from otelms.domain.repositories.database import get_db_session
from otelms.services.sync_service import SyncService


async def main() -> None:
    settings = get_settings()
    service = SyncService(
        hotel_id="18330",
        username=settings.otelms_default_username,
        password=settings.otelms_default_password,
    )
    result = await service.sync_calendar()

    print(
        f"success={result.success} availability={result.availability_persisted} "
        f"created={result.records_created} updated={result.records_updated} "
        f"errors={result.errors}"
    )

    async with get_db_session() as session:
        repo = CategoryAvailabilityRepository(session)
        rows = await repo.get_range("18330", date(2020, 1, 1), date(2035, 1, 1))

    per_cat = Counter(r.category_id for r in rows)
    days = sorted({r.date for r in rows})
    print(f"filas en BD: {len(rows)} | rango {days[0]} .. {days[-1]} ({len(days)} días)")
    print(f"por categoría: {sorted(per_cat.items())}")
    print(f"disponibles por día (total): {sum(r.available for r in rows)}")


asyncio.run(main())