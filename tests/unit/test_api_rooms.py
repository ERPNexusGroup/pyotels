"""
Tests for room availability endpoints: disponibles / ocupadas / checkouts.

Cubre los nuevos métodos de repositorio (RoomRepository.get_occupied_for_date,
ReservationRepository.get_checkins/checkouts_for_date) y los endpoints HTTP
de otelms.api.routes.rooms con TestClient + dependency_overrides.
"""
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otelms.api import dependencies as deps
from otelms.api.main import app
from otelms.domain.repositories import (
    CategoryRepository,
    GuestRepository,
    HotelRepository,
    ReservationRepository,
    RoomRepository,
)


@pytest_asyncio.fixture
async def session(test_engine):
    """Create test session (sin commit: cada test queda aislado)."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def repos(session):
    return {
        "hotel": HotelRepository(session),
        "category": CategoryRepository(session),
        "room": RoomRepository(session),
        "guest": GuestRepository(session),
        "reservation": ReservationRepository(session),
    }


def _dt(day: int, hour: int = 14, month: int = 3) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


async def seed_hotel(repos, hotel_id: str = "h1"):
    """Hotel con 2 categorías, 3 habitaciones y reservas de varios estados."""
    await repos["hotel"].create(
        id=hotel_id, name="Hotel 1", domain="otelms.com",
        username="u@u.com", password_hash="h",
    )
    await repos["category"].create(id="std", hotel_id=hotel_id, name="Standard")
    await repos["category"].create(id="dlx", hotel_id=hotel_id, name="Deluxe")
    await repos["room"].create(id="r101", hotel_id=hotel_id, category_id="std", name="101")
    await repos["room"].create(id="r102", hotel_id=hotel_id, category_id="std", name="102")
    await repos["room"].create(id="r201", hotel_id=hotel_id, category_id="dlx", name="201")
    await repos["guest"].create(
        id="g1", hotel_id=hotel_id, first_name="John", last_name="Doe",
    )
    # Ocupada: check-in vigente 10/03 -> 13/03 (status 2)
    await repos["reservation"].create(
        id="res_occ", hotel_id=hotel_id, room_id="r101", guest_id="g1",
        check_in=_dt(10), check_out=_dt(13, 11), status=2, adults=2,
    )
    # Llegada futura: reserva 12/03 -> 14/03 (status 1, bloquea disponibilidad pero no ocupa)
    await repos["reservation"].create(
        id="res_arr", hotel_id=hotel_id, room_id="r102", guest_id="g1",
        check_in=_dt(12), check_out=_dt(14, 11), status=1,
    )
    # Cancelada solapada: no debe bloquear ni ocupar
    await repos["reservation"].create(
        id="res_can", hotel_id=hotel_id, room_id="r201", guest_id="g1",
        check_in=_dt(11), check_out=_dt(13, 11), status=4,
    )
    return hotel_id


# ============================================================
# Repository tests
# ============================================================

class TestAvailableForDates:
    async def test_excludes_overlapping(self, repos):
        await seed_hotel(repos)
        # Rango 11/03 -> 13/03: r101 bloqueada (status 2), r102 bloqueada (status 1)
        available = await repos["room"].get_available_for_dates("h1", "2026-03-11", "2026-03-13")
        assert [r.id for r in available] == ["r201"]

    async def test_cancelled_does_not_block(self, repos):
        await seed_hotel(repos)
        # r201 solo tiene reserva cancelada -> disponible
        available = await repos["room"].get_available_for_dates("h1", "2026-03-11", "2026-03-12")
        assert "r201" in [r.id for r in available]

    async def test_no_overlap_all_available(self, repos):
        await seed_hotel(repos)
        available = await repos["room"].get_available_for_dates("h1", "2026-04-01", "2026-04-05")
        assert sorted(r.id for r in available) == ["r101", "r102", "r201"]


class TestOccupiedForDate:
    async def test_occupied_only_checked_in(self, repos):
        await seed_hotel(repos)
        # 12/03: res_occ en casa (status 2); res_arr es status 1 -> no ocupa
        occupied = await repos["room"].get_occupied_for_date("h1", date(2026, 3, 12))
        assert [r.id for r in occupied] == ["res_occ"]
        assert occupied[0].room.id == "r101"
        assert occupied[0].guest.first_name == "John"

    async def test_checkout_day_still_occupied(self, repos):
        await seed_hotel(repos)
        # El día de salida (13/03) la habitación sigue ocupada hasta el check-out
        occupied = await repos["room"].get_occupied_for_date("h1", date(2026, 3, 13))
        assert [r.id for r in occupied] == ["res_occ"]

    async def test_after_checkout_empty(self, repos):
        await seed_hotel(repos)
        occupied = await repos["room"].get_occupied_for_date("h1", date(2026, 3, 14))
        assert list(occupied) == []

    async def test_accepts_str_date(self, repos):
        await seed_hotel(repos)
        occupied = await repos["room"].get_occupied_for_date("h1", "2026-03-12")
        assert [r.id for r in occupied] == ["res_occ"]


class TestCheckinsCheckoutsForDate:
    async def test_checkouts_for_date(self, repos):
        await seed_hotel(repos)
        out = await repos["reservation"].get_checkouts_for_date("h1", date(2026, 3, 13))
        assert [r.id for r in out] == ["res_occ"]
        assert await repos["reservation"].get_checkouts_for_date("h1", date(2026, 3, 12)) == []

    async def test_checkins_for_date(self, repos):
        await seed_hotel(repos)
        inn = await repos["reservation"].get_checkins_for_date("h1", date(2026, 3, 12))
        assert [r.id for r in inn] == ["res_arr"]

    async def test_today_shortcuts_backward_compatible(self, repos):
        """get_today_* delegan a las versiones con fecha (hoy por defecto)."""
        await seed_hotel(repos)
        today = date.today()
        await repos["reservation"].create(
            id="res_in_today", hotel_id="h1", room_id="r201", guest_id="g1",
            check_in=datetime(today.year, today.month, today.day, 14, 0, tzinfo=UTC),
            check_out=_dt(20, 11, month=12), status=1,
        )
        await repos["reservation"].create(
            id="res_out_today", hotel_id="h1", room_id="r102", guest_id="g1",
            check_in=_dt(1, 14, month=1),
            check_out=datetime(today.year, today.month, today.day, 11, 0, tzinfo=UTC),
            status=2,
        )
        checkins = await repos["reservation"].get_today_checkins("h1")
        checkouts = await repos["reservation"].get_today_checkouts("h1")
        assert "res_in_today" in [r.id for r in checkins]
        assert "res_out_today" in [r.id for r in checkouts]


# ============================================================
# HTTP tests (rooms router)
# ============================================================

@pytest.fixture
def api_client(test_session):
    """TestClient con auth y repos apuntando a la sesión de test."""
    old = dict(app.dependency_overrides)
    app.dependency_overrides[deps.verify_api_key] = lambda: None
    app.dependency_overrides[deps.get_room_repo] = lambda: RoomRepository(test_session)
    app.dependency_overrides[deps.get_category_repo] = lambda: CategoryRepository(test_session)
    app.dependency_overrides[deps.get_reservation_repo] = lambda: ReservationRepository(test_session)
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


@pytest_asyncio.fixture
async def seeded(test_session):
    r = {
        "hotel": HotelRepository(test_session),
        "category": CategoryRepository(test_session),
        "room": RoomRepository(test_session),
        "guest": GuestRepository(test_session),
        "reservation": ReservationRepository(test_session),
    }
    await seed_hotel(r)
    return r


class TestRoomsHttp:
    def test_list_rooms(self, api_client, seeded):
        resp = api_client.get("/rooms", params={"hotel_id": "h1"})
        assert resp.status_code == 200
        assert sorted(r["id"] for r in resp.json()) == ["r101", "r102", "r201"]

    def test_available(self, api_client, seeded):
        resp = api_client.get("/rooms/available", params={
            "hotel_id": "h1", "check_in": "2026-03-11", "check_out": "2026-03-13",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_rooms"] == 3
        assert data["available_count"] == 1
        assert data["occupied_count"] == 2
        assert data["occupancy_rate"] == pytest.approx(66.7)
        assert [r["id"] for r in data["items"]] == ["r201"]
        by_cat = {c["category_id"]: c for c in data["by_category"]}
        assert by_cat["std"] == {"category_id": "std", "category_name": "Standard",
                                 "total": 2, "available": 0, "occupied": 2}
        assert by_cat["dlx"]["available"] == 1

    def test_available_invalid_range(self, api_client, seeded):
        resp = api_client.get("/rooms/available", params={
            "hotel_id": "h1", "check_in": "2026-03-13", "check_out": "2026-03-13",
        })
        assert resp.status_code == 400

    def test_available_missing_params(self, api_client, seeded):
        resp = api_client.get("/rooms/available", params={"hotel_id": "h1"})
        assert resp.status_code == 422

    def test_occupied(self, api_client, seeded):
        resp = api_client.get("/rooms/occupied", params={
            "hotel_id": "h1", "target_date": "2026-03-12",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-03-12"
        assert data["occupied_count"] == 1
        item = data["items"][0]
        assert item["reservation_id"] == "res_occ"
        assert item["room"]["id"] == "r101"
        assert item["guest_name"] == "John Doe"
        assert item["nights_remaining"] == 1

    def test_occupied_defaults_to_today(self, api_client, seeded):
        resp = api_client.get("/rooms/occupied", params={"hotel_id": "h1"})
        assert resp.status_code == 200
        assert resp.json()["date"] == date.today().isoformat()

    def test_checkouts(self, api_client, seeded):
        resp = api_client.get("/rooms/checkouts", params={
            "hotel_id": "h1", "target_date": "2026-03-13",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["reservation_id"] == "res_occ"
        assert data["items"][0]["room"]["id"] == "r101"

    def test_checkouts_empty_day(self, api_client, seeded):
        resp = api_client.get("/rooms/checkouts", params={
            "hotel_id": "h1", "target_date": "2026-03-12",
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_requires_api_key(self, api_client, seeded):
        """Sin API key (override removido) debe fallar con 422/401, sin tocar la BD."""
        old = dict(app.dependency_overrides)
        app.dependency_overrides.pop(deps.verify_api_key, None)
        try:
            resp = api_client.get("/rooms/available", params={"hotel_id": "h1"})
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)
        assert resp.status_code in (401, 422)

    async def test_room_without_category_uses_sentinel(self, api_client, test_session):
        """Habitación con category_id NULL no rompe: usa sentinel 'uncategorized'."""
        room_repo = RoomRepository(test_session)
        await room_repo.create(id="r999", hotel_id="h1", category_id=None, name="999")

        resp = api_client.get("/rooms", params={"hotel_id": "h1"})
        assert resp.status_code == 200
        r999 = [r for r in resp.json() if r["id"] == "r999"]
        assert len(r999) == 1
        assert r999[0]["category_id"] == "uncategorized"
        assert r999[0]["category"] is None

        resp = api_client.get("/rooms/available", params={
            "hotel_id": "h1", "check_in": "2026-04-01", "check_out": "2026-04-05",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "r999" in [r["id"] for r in data["items"]]
        assert "uncategorized" in [c["category_id"] for c in data["by_category"]]
