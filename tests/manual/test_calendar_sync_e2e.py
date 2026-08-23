"""Test E2E: extrae reservas del HTML y persiste en BD async (aiosqlite)."""
import asyncio
import hashlib
import json
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from otelms.config.settings import get_settings
from otelms.domain.entities import Base, Reservation
from otelms.scraping.calendar_extract import extract_all_reservations
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


async def test_extract_to_db():
    """Extrae del HTML y persiste directamente en BD async."""
    settings = get_settings()

    # Engine async
    db_url = settings.database_url
    # Asegurarnos que es aiosqlite
    if "sqlite:///" in db_url and "+aiosqlite" not in db_url:
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Leer HTML guardado
        with open("calendario_debug.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        # Extraer
        reservations = extract_all_reservations(html_content)
        print(f"Total extracted: {len(reservations)}")
        if not reservations:
            print("❌ No se extrajeron reservas")
            return

        # Persistir (upsert)
        created = 0
        updated = 0
        for res in reservations:
            data = _map_reservation(res)
            sync_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode()
            ).hexdigest()[:64]

            existing = await session.get(Reservation, str(res["resid"]))
            if existing:
                existing.sync_hash = sync_hash
                existing.last_synced_at = datetime.utcnow()
                for k, v in data.items():
                    if k != "id":
                        setattr(existing, k, v)
                await session.merge(existing)
                updated += 1
            else:
                session.add(Reservation(
                    id=str(res["resid"]),
                    hotel_id="18330",
                    room_id="room_default",
                    check_in=data["check_in"],
                    check_out=data["check_out"],
                    status=data["status"],
                    adults=data["adults"],
                    source=data["source"],
                    notes=data["notes"],
                    sync_hash=sync_hash,
                    last_synced_at=datetime.utcnow(),
                    otelms_created_at=data["otelms_created_at"],
                    otelms_updated_at=data["otelms_updated_at"],
                ))
                created += 1

        await session.commit()

        # Verificar
        result = await session.execute(
            select(Reservation).where(Reservation.hotel_id == "18330")
        )
        all_res = result.scalars().all()
        print(f"\n✅ Persistidos: {created} creadas, {updated} actualizadas")
        print(f"📊 Total en BD: {len(all_res)} reservas")

        if all_res:
            sample = all_res[0]
            print(f"  Sample: id={sample.id} check_in={sample.check_in} status={sample.status}")

    await engine.dispose()


def _map_reservation(res: dict) -> dict:
    def parse_date(s):
        if not s or s.strip() in ("0000-00-00", "0000-00-00 00:00:00"):
            return None
        try:
            return datetime.fromisoformat(s.strip())
        except (ValueError, TypeError):
            return None

    return {
        "check_in": parse_date(res.get("check_in", "")),
        "check_out": parse_date(res.get("check_out", "")),
        "status": res.get("status", 1),
        "adults": res.get("guest_count", 1) or 1,
        "source": res.get("channel", ""),
        "notes": res.get("comments", ""),
        "otelms_created_at": parse_date(res.get("created_at")),
        "otelms_updated_at": parse_date(res.get("modified_at")),
    }


if __name__ == "__main__":
    asyncio.run(test_extract_to_db())