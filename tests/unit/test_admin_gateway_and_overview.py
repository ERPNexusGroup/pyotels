"""Unit tests for admin gateway status and hotel overview endpoints."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.main import app
from otelms.api.routes.admin.auth import _get_db
from otelms.config.settings import settings
from otelms.domain.entities import (
    Category,
    CategoryAvailability,
    ChannelRate,
    Hotel,
    PropertyService,
    Reservation,
    Room,
    SyncLog,
)


client = TestClient(app)


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


@pytest.fixture(autouse=True)
def _enable_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_enable_admin_routes", True)
    monkeypatch.setattr(settings, "api_enable_read_public", True)
    monkeypatch.setattr(settings, "api_enable_internal_sync", True)
    monkeypatch.setattr(settings, "api_enable_write_actions", False)
    monkeypatch.setattr(settings, "api_enable_legacy_routes", False)


def test_get_gateway_status_returns_flags_redis_and_default_hotel():
    resp = client.get("/admin/api/gateway-status", headers={"Authorization": f"Bearer {_admin_token()}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "flags" in data and "redis" in data and "default_hotel_id" in data
    assert set(data["flags"].keys()) == {
        "api_enable_read_public",
        "api_enable_internal_sync",
        "api_enable_write_actions",
        "api_enable_admin_routes",
        "api_enable_legacy_routes",
    }
    assert isinstance(data["redis"].get("connected"), bool)
    assert data["redis"].get("mode") in {"redis", "memory_fallback", "unknown"}
    # default hotel id comes from settings (commonly 18330)
    assert isinstance(data["default_hotel_id"], (str, type(None)))


def test_patch_gateway_status_updates_flags_and_cannot_disable_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_enable_read_public", True)
    monkeypatch.setattr(settings, "api_enable_internal_sync", True)
    monkeypatch.setattr(settings, "api_enable_write_actions", False)
    monkeypatch.setattr(settings, "api_enable_legacy_routes", False)
    monkeypatch.setattr(settings, "api_enable_admin_routes", True)

    resp = client.patch(
        "/admin/api/gateway-status",
        headers={"Authorization": f"Bearer {_admin_token()}"},
        json={
            "api_enable_read_public": False,
            "api_enable_internal_sync": False,
            "api_enable_write_actions": True,
            "api_enable_legacy_routes": True,
            "api_enable_admin_routes": False,  # must be ignored/forced true
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["flags"]["api_enable_read_public"] is False
    assert data["flags"]["api_enable_internal_sync"] is False
    assert data["flags"]["api_enable_write_actions"] is True
    assert data["flags"]["api_enable_legacy_routes"] is True
    assert data["flags"]["api_enable_admin_routes"] is True
    assert settings.api_enable_admin_routes is True


@pytest.fixture
async def _overview_seed(test_session: AsyncSession):
    hid = "18330"
    # cleanup
    await test_session.execute(delete(SyncLog).where(SyncLog.hotel_id == hid))
    await test_session.execute(delete(ChannelRate).where(ChannelRate.hotel_id == hid))
    await test_session.execute(delete(CategoryAvailability).where(CategoryAvailability.hotel_id == hid))
    await test_session.execute(delete(PropertyService).where(PropertyService.hotel_id == hid))
    await test_session.execute(delete(Reservation).where(Reservation.hotel_id == hid))
    await test_session.execute(delete(Room).where(Room.hotel_id == hid))
    await test_session.execute(delete(Category).where(Category.hotel_id == hid))
    await test_session.execute(delete(Hotel).where(Hotel.id == hid))
    await test_session.commit()

    hotel = Hotel(id=hid, name="Hotel Ensueños", domain="otelms.com", username="u", password_hash="x", is_active=True)
    cat = Category(id="cat1", hotel_id=hid, name="Std")
    room = Room(id="r1", hotel_id=hid, category_id="cat1", name="101", is_active=True)
    test_session.add_all([hotel, cat, room])
    await test_session.flush()

    from datetime import date
    today_d = date.today()
    start_today = datetime.combine(today_d, datetime.min.time()).replace(tzinfo=UTC)
    end_today = datetime.combine(today_d, datetime.max.time()).replace(tzinfo=UTC)
    mid_today = start_today + timedelta(hours=12)
    # in-house: check_in <= today_start < check_out, not cancelled
    test_session.add(Reservation(
        id="res_inhouse", hotel_id=hid, room_id="r1", guest_id=None,
        check_in=start_today - timedelta(days=1), check_out=start_today + timedelta(days=1),
        status=1, adults=1, children=0, babies=0, total_price=Decimal("100.00"), currency="USD",
    ))
    # arrival today
    test_session.add(Reservation(
        id="res_arr", hotel_id=hid, room_id="r1", guest_id=None,
        check_in=start_today + timedelta(hours=14), check_out=start_today + timedelta(days=2),
        status=1, adults=1, children=0, babies=0, total_price=Decimal("50.00"), currency="USD",
    ))
    # departure today
    test_session.add(Reservation(
        id="res_dep", hotel_id=hid, room_id="r1", guest_id=None,
        check_in=start_today - timedelta(days=2), check_out=start_today + timedelta(hours=11),
        status=1, adults=1, children=0, babies=0, total_price=Decimal("75.00"), currency="USD",
    ))
    # negative price
    test_session.add(Reservation(
        id="res_neg", hotel_id=hid, room_id="r1", guest_id=None,
        check_in=start_today + timedelta(days=5), check_out=start_today + timedelta(days=6),
        status=1, adults=1, children=0, babies=0, total_price=Decimal("-10.00"), currency="USD",
    ))
    # cancelled should be excluded from operational in-house/arrival/departure logic
    test_session.add(Reservation(
        id="res_cancel", hotel_id=hid, room_id="r1", guest_id=None,
        check_in=start_today - timedelta(days=1), check_out=start_today + timedelta(days=2),
        status=4, adults=1, children=0, babies=0, total_price=Decimal("20.00"), currency="USD",
    ))

    test_session.add(ChannelRate(id="cr1", hotel_id=hid, category_id="cat1", rate_id="1", channel="direct", date=today_d, price=Decimal("99.00"), currency="USD"))
    test_session.add(CategoryAvailability(id="ca1", hotel_id=hid, category_id="cat1", date=today_d, available=3))
    test_session.add(PropertyService(id="ps1", hotel_id=hid, name="wifi", label="WiFi", is_active=True))
    for i in range(16):
        test_session.add(SyncLog(hotel_id=hid, sync_type="calendar", status="completed", started_at=datetime.now(UTC) - timedelta(minutes=i), records_created=1, records_updated=0, records_processed=1, error_count=0))

    await test_session.commit()
    yield hid

    await test_session.execute(delete(SyncLog).where(SyncLog.hotel_id == hid))
    await test_session.execute(delete(ChannelRate).where(ChannelRate.hotel_id == hid))
    await test_session.execute(delete(CategoryAvailability).where(CategoryAvailability.hotel_id == hid))
    await test_session.execute(delete(PropertyService).where(PropertyService.hotel_id == hid))
    await test_session.execute(delete(Reservation).where(Reservation.hotel_id == hid))
    await test_session.execute(delete(Room).where(Room.hotel_id == hid))
    await test_session.execute(delete(Category).where(Category.hotel_id == hid))
    await test_session.execute(delete(Hotel).where(Hotel.id == hid))
    await test_session.commit()


async def test_get_hotel_overview_returns_operational_health_and_recent_syncs(test_session: AsyncSession, _overview_seed: str):
    async def _override_db():
        yield test_session
    app.dependency_overrides[_get_db] = _override_db
    try:
        resp = client.get("/admin/api/hotel-overview?hotel_id=18330", headers={"Authorization": f"Bearer {_admin_token()}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["hotel_id"] == "18330"
        assert "operational" in data and "data_health" in data and "recent_syncs" in data
        op = data["operational"]
        dh = data["data_health"]
        assert set(op.keys()) >= {"arrivals_today", "departures_today", "in_house_today", "reservations_pending_balance"}
        assert set(dh.keys()) >= {"reservations_total", "reservations_negative_total_price", "channel_rates", "category_availability", "property_services"}
        assert op["in_house_today"] >= 1
        assert op["arrivals_today"] >= 1
        assert op["departures_today"] >= 1
        assert dh["reservations_total"] >= 5
        assert dh["reservations_negative_total_price"] >= 1
        assert dh["channel_rates"] >= 1
        assert dh["category_availability"] >= 1
        assert dh["property_services"] >= 1
        assert isinstance(data["recent_syncs"], list)
        assert len(data["recent_syncs"]) <= 15
    finally:
        app.dependency_overrides.clear()
