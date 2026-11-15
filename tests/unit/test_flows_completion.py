"""Unit and integration tests for completed Pyotels flows (billing, housekeeping, cache, rate limits, admin)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from otelms.api.dependencies import _live_rate_windows, verify_api_key
from otelms.api.main import app
from otelms.api.mappers import compute_billing_summary
from otelms.api.routes.housekeeping import get_housekeeping, update_housekeeping_status
from otelms.api.schemas import HousekeepingStatusUpdate
from otelms.config.settings import settings
from otelms.domain.entities import (
    ApiKey,
    Base,
    Category,
    Guest,
    Hotel,
    Payment,
    Reservation,
    Room,
    RoomAvailability,
    Service,
)
from otelms.domain.repositories import (
    HousekeepingStatusRepository,
    ReservationRepository,
    RoomRepository,
)
from otelms.scraping.folio_deep_extract import parse_folio_complete
from otelms.utils.cache import CacheManager, MemoryCacheBackend


def _admin_token() -> str:
    now = datetime.now(UTC)
    return jose_jwt.encode(
        {
            "sub": "test_admin",
            "name": "Test Admin",
            "role": "admin",
            "iat": now,
            "exp": now + timedelta(hours=12),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


async def _make_memory_session() -> tuple[async_sessionmaker[AsyncSession], object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker, engine


def test_folio_extract_guest_address_and_document():
    html = """
    <html><body>
    <div class="nameofgroup">Reserva № 9001</div>
    <div class="balans">Saldo: $12.50</div>
    <div class="panel">
        <div class="panel-heading">Información básica</div>
        <table>
            <tr><td>Huésped:</td><td>Ana Gómez</td></tr>
            <tr><td>Dirección:</td><td>Av. Amazonas 123, Quito</td></tr>
            <tr><td>Documento:</td><td>Cédula 1712345678</td></tr>
        </table>
    </div>
    <table id="tbl_guests">
        <thead><tr><th>Nombre</th><th>Documento</th><th>Dirección</th></tr></thead>
        <tbody>
            <tr><td>Ana Gómez</td><td>PAS-998877</td><td>Av. Patria 456</td></tr>
        </tbody>
    </table>
    </body></html>
    """
    data = parse_folio_complete(html, reservation_id="9001")
    assert data["basic"]["address"] == "Av. Amazonas 123, Quito"
    assert data["basic"]["document_number"] == "Cédula 1712345678"
    assert data["guests"][0]["document_number"] == "PAS-998877"
    assert data["guests"][0]["address"] == "Av. Patria 456"


def test_compute_billing_summary_decimal_and_cents():
    now = datetime.now(UTC)
    res = Reservation(
        id="r1",
        hotel_id="18330",
        total_price=Decimal("100.00"),
        otelms_balance=Decimal("75.55"),
        deep_synced_at=now,
        status=1,
        services=[
            Service(id="s1", reservation_id="r1", date=now, price=Decimal("100.00"), title="Alojamiento", total=Decimal("100.00")),
            Service(id="s2", reservation_id="r1", date=now, price=Decimal("25.55"), title="Lavandería", total=Decimal("25.55")),
        ],
        payments=[
            Payment(id="p1", reservation_id="r1", date=now, amount=Decimal("50.00")),
        ],
    )
    dec_summary = compute_billing_summary(res, money_unit="decimal")
    assert dec_summary["money_unit"] == "decimal"
    assert dec_summary["accommodation_total"] == Decimal("100.00")
    assert dec_summary["services_total"] == Decimal("25.55")
    assert dec_summary["payments_total"] == Decimal("50.00")
    assert dec_summary["computed_balance"] == Decimal("75.55")
    assert dec_summary["otelms_balance"] == Decimal("75.55")
    assert dec_summary["balance_mismatch"] is False
    assert dec_summary["is_billable"] is False

    cents_summary = compute_billing_summary(res, money_unit="cents")
    assert cents_summary["money_unit"] == "cents"
    assert cents_summary["accommodation_total"] == 10000
    assert cents_summary["services_total"] == 2555
    assert cents_summary["payments_total"] == 5000
    assert cents_summary["computed_balance"] == 7555

    # Settled reservation with matching balance is billable
    res.payments.append(Payment(id="p2", reservation_id="r1", date=now, amount=Decimal("75.55")))
    res.otelms_balance = Decimal("0.00")
    settled_summary = compute_billing_summary(res, money_unit="decimal")
    assert settled_summary["balance_mismatch"] is False
    assert settled_summary["is_billable"] is True

    # Mismatch detection
    res.otelms_balance = Decimal("70.00")
    mismatch_summary = compute_billing_summary(res, money_unit="decimal")
    assert mismatch_summary["balance_mismatch"] is True
    assert mismatch_summary["is_billable"] is False


@pytest.mark.asyncio
async def test_reservation_note_keyword_filter():
    maker, engine = await _make_memory_session()
    try:
        async with maker() as session:
            session.add(Hotel(id="18330", name="H", domain="d", username="u", password_hash="x"))
            session.add(Category(id="1", hotel_id="18330", name="Matrimonial"))
            session.add(Room(id="101", hotel_id="18330", category_id="1", name="101"))
            session.add(Guest(id="g1", hotel_id="18330", first_name="Guest", last_name="One"))
            session.add(
                Reservation(
                    id="res_cf",
                    hotel_id="18330",
                    guest_id="g1",
                    room_id="101",
                    check_in=datetime(2026, 11, 10, tzinfo=UTC),
                    check_out=datetime(2026, 11, 12, tzinfo=UTC),
                    notes="Cliente solicita CF urgente",
                )
            )
            session.add(
                Reservation(
                    id="res_other",
                    hotel_id="18330",
                    guest_id="g1",
                    room_id="101",
                    check_in=datetime(2026, 11, 10, tzinfo=UTC),
                    check_out=datetime(2026, 11, 12, tzinfo=UTC),
                    notes="Sin factura",
                )
            )
            await session.commit()

            repo = ReservationRepository(session)
            items = await repo.get_by_hotel("18330", note_keyword="CF")
            count = await repo.count_by_hotel("18330", note_keyword="CF")
            assert [r.id for r in items] == ["res_cf"]
            assert count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_housekeeping_dusting_and_last_cleaned_at():
    maker, engine = await _make_memory_session()
    try:
        async with maker() as session:
            session.add(Hotel(id="18330", name="H", domain="d", username="u", password_hash="x"))
            session.add(Category(id="1", hotel_id="18330", name="Matrimonial"))
            session.add(Category(id="21", hotel_id="18330", name="Overbooking"))

            old_clean = datetime.now(UTC) - timedelta(days=5)
            recent_clean = datetime.now(UTC) - timedelta(days=1)

            session.add_all(
                [
                    Room(id="101", hotel_id="18330", category_id="1", name="101", is_active=True, last_cleaned_at=old_clean),
                    Room(id="102", hotel_id="18330", category_id="1", name="102", is_active=True, last_cleaned_at=recent_clean),
                    Room(id="103", hotel_id="18330", category_id="1", name="103", is_active=True, last_cleaned_at=old_clean),
                    Room(id="999", hotel_id="18330", category_id="21", name="OB", is_active=True, last_cleaned_at=old_clean),
                ]
            )
            target = date(2026, 11, 14)
            # Room 103 is blocked for maintenance on target date
            session.add(
                RoomAvailability(
                    id="avail_103",
                    hotel_id="18330",
                    room_id="103",
                    start_date=datetime(2026, 11, 14, 0, 0, tzinfo=UTC),
                    end_date=datetime(2026, 11, 15, 0, 0, tzinfo=UTC),
                    is_blocked=True,
                    reason="Mantenimiento",
                )
            )
            await session.commit()

            res_repo = ReservationRepository(session)
            room_repo = RoomRepository(session)
            hk_repo = HousekeepingStatusRepository(session)

            hk = await get_housekeeping(
                hotel_id="18330",
                target_date=target,
                res_repo=res_repo,
                room_repo=room_repo,
                hk_repo=hk_repo,
                session=session,
            )
            dusting_ids = [r.room_id for r in hk.dusting_rooms]
            assert dusting_ids == ["101"]

            # Mark 101 as cleaned with notes -> updates last_cleaned_at and excludes from dusting_rooms
            upd = await update_housekeeping_status(
                room_id="101",
                body=HousekeepingStatusUpdate(status=2, updated_by="Maria", notes="Polvo limpiado"),
                hotel_id="18330",
                target_date=target,
                room_repo=room_repo,
                hk_repo=hk_repo,
            )
            assert upd.status == 2
            assert upd.notes == "Polvo limpiado"
            await session.commit()

            room_101 = await room_repo.get_by_id("101")
            assert room_101 is not None
            assert room_101.last_cleaned_at is not None

            hk_after = await get_housekeeping(
                hotel_id="18330",
                target_date=target,
                res_repo=res_repo,
                room_repo=room_repo,
                hk_repo=hk_repo,
                session=session,
            )
            assert hk_after.dusting_rooms == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_memory_cache_ttl_and_reconnect_redis():
    backend = MemoryCacheBackend(max_entries=2)
    await backend.set("k1", "v1", ttl=60)
    await backend.set("k2", "v2", ttl=0)  # Immediately expired
    assert await backend.get("k1") == "v1"
    assert await backend.get("k2") is None

    # Eviction check when exceeding max_entries
    await backend.set("k3", "v3", ttl=60)
    await backend.set("k4", "v4", ttl=60)
    assert await backend.get("k1") is None
    assert await backend.get("k4") == "v4"

    mgr = CacheManager()
    mgr._backend = backend
    mgr._use_redis = False

    fake_client = AsyncMock()
    fake_client.ping = AsyncMock(return_value=True)
    with patch("otelms.utils.cache.RedisCache") as mock_redis_cls:
        mock_instance = AsyncMock()
        mock_instance.client = fake_client
        mock_redis_cls.return_value = mock_instance
        ok = await mgr.reconnect_redis()
        assert ok is True
        assert mgr.use_redis is True


def test_live_endpoint_cache_and_429_rate_limit(monkeypatch):
    _live_rate_windows.clear()
    monkeypatch.setattr(settings, "live_endpoint_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "api_enable_read_public", True)
    app.dependency_overrides[verify_api_key] = lambda: ApiKey(
        id="test-key", name="test", key_hash="h", is_active=True, rate_limit=60
    )

    fetch_mock = AsyncMock(
        return_value={
            "status_date": "2026-11-14",
            "departures_today": 1,
            "arrivals_today": 2,
            "inhouse_today": 3,
        }
    )

    class _DummyExtractor:
        def __init__(self, hotel_id: str) -> None:
            self.hotel_id = hotel_id

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        fetch_status = fetch_mock

    mem_cache = CacheManager()
    mem_cache._backend = MemoryCacheBackend()
    mem_cache._use_redis = False

    try:
        with (
            patch("otelms.api.routes.hotels.SetupExtractor", _DummyExtractor),
            patch("otelms.api.routes.hotels.get_cache", AsyncMock(return_value=mem_cache)),
        ):
            client = TestClient(app)
            r1 = client.get("/hotels/18330/status")
            r2 = client.get("/hotels/18330/status")
            r3 = client.get("/hotels/18330/status")

            assert r1.status_code == 200
            assert r2.status_code == 200
            # Second call was served from 60s cache
            assert fetch_mock.await_count == 1
            # Third call hits per-route rate limit
            assert r3.status_code == 429
            assert "Retry-After" in r3.headers
    finally:
        app.dependency_overrides.clear()
        _live_rate_windows.clear()


def test_admin_workers_forbidden_when_debug_false(monkeypatch):
    monkeypatch.setattr(settings, "app_debug", False)
    monkeypatch.setattr(settings, "api_enable_admin_routes", True)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_admin_token()}"}

    r_status = client.get("/admin/api/workers/status", headers=headers)
    r_start = client.post("/admin/api/workers/start", headers=headers)
    r_stop = client.post("/admin/api/workers/stop", headers=headers)

    assert r_status.status_code == 403
    assert r_start.status_code == 403
    assert r_stop.status_code == 403
