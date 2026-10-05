"""
Tests de serialización de relaciones en los endpoints que exponen esquemas anidados.

Los esquemas (`GuestResponse.full_name`, `CategoryResponse.rooms`, `RoomResponse.category`,
`ReservationResponse.{guest,room,services,payments}`) se serializan con
from_attributes=True sobre entidades ORM. Si una relación no viene precargada en la
sentencia, el acceso diferido dispara MissingGreenlet y el endpoint responde 500.

Cada test reproduce uno de esos 500 y comprueba que ahora responde 200 con las
relaciones pobladas.
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from otelms.api import dependencies as deps
from otelms.api.main import app
from otelms.domain.repositories import (
    CategoryRepository,
    GuestRepository,
    HotelRepository,
    ReservationRepository,
    RoomRepository,
)

HOTEL = "h1"


def _dt(day: int, hour: int = 14, month: int = 3) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def seeded(test_session):
    """Hotel mínimo con categoría, habitación, huésped y reserva."""
    hotel = HotelRepository(test_session)
    category = CategoryRepository(test_session)
    room = RoomRepository(test_session)
    guest = GuestRepository(test_session)
    reservation = ReservationRepository(test_session)

    await hotel.create(
        id=HOTEL, name="Hotel 1", domain="otelms.com",
        username="u@u.com", password_hash="h",
    )
    await category.create(id="std", hotel_id=HOTEL, name="Standard", sort_order=1)
    await room.create(id="r101", hotel_id=HOTEL, category_id="std", name="101")
    await guest.create(
        id="g1", hotel_id=HOTEL, first_name="John", middle_name="Q",
        last_name="Doe", email="john@example.com",
    )
    await reservation.create(
        id="res1", hotel_id=HOTEL, room_id="r101", guest_id="g1",
        check_in=_dt(10), check_out=_dt(13, 11), status=2, adults=2,
        total_price=250.0, currency="USD",
    )
    return {
        "hotel": hotel, "category": category, "room": room,
        "guest": guest, "reservation": reservation,
    }


@pytest.fixture
def api_client(test_session):
    """TestClient con auth desactivada y repos apuntando a la sesión de test."""
    old = dict(app.dependency_overrides)
    app.dependency_overrides[deps.verify_api_key] = lambda: None
    app.dependency_overrides[deps.get_room_repo] = lambda: RoomRepository(test_session)
    app.dependency_overrides[deps.get_category_repo] = lambda: CategoryRepository(test_session)
    app.dependency_overrides[deps.get_reservation_repo] = lambda: ReservationRepository(test_session)
    app.dependency_overrides[deps.get_guest_repo] = lambda: GuestRepository(test_session)
    app.dependency_overrides[deps.get_hotel_repo] = lambda: HotelRepository(test_session)
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


class TestGuests:
    """GuestResponse.full_name es obligatorio: la entidad debe exponerlo."""

    def test_list_guests_returns_full_name(self, api_client, seeded):
        resp = api_client.get("/guests", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        assert data[0]["full_name"] == "John Q Doe"

    async def test_full_name_skips_empty_parts(self, api_client, test_session, seeded):
        await GuestRepository(test_session).create(
            id="g2", hotel_id=HOTEL, first_name="Ana", last_name="Ruiz",
        )
        resp = api_client.get("/guests", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        names = {g["id"]: g["full_name"] for g in resp.json()}
        assert names["g2"] == "Ana Ruiz"

    async def test_full_name_normalizes_otelms_padding(self, api_client, test_session, seeded):
        """OtelMS devuelve los apellidos con espacio inicial: "CELI" + " JOFRE"."""
        await GuestRepository(test_session).create(
            id="g3", hotel_id=HOTEL, first_name="CELI", last_name=" JOFRE",
        )
        resp = api_client.get("/guests", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        names = {g["id"]: g["full_name"] for g in resp.json()}
        assert names["g3"] == "CELI JOFRE"


class TestCategories:
    """CategoryResponse.rooms se serializa sobre la relación `rooms`."""

    def test_list_categories_includes_rooms(self, api_client, seeded):
        resp = api_client.get("/categories", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "std"
        assert [r["id"] for r in data[0]["rooms"]] == ["r101"]

    def test_with_rooms_param_still_accepted(self, api_client, seeded):
        """El parámetro histórico no debe romper clientes ni cambiar el resultado."""
        resp = api_client.get(
            "/categories", params={"hotel_id": HOTEL, "with_rooms": False}
        )
        assert resp.status_code == 200, resp.text
        assert [r["id"] for r in resp.json()[0]["rooms"]] == ["r101"]

    def test_get_category_includes_rooms(self, api_client, seeded):
        resp = api_client.get("/categories/std", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        assert [r["id"] for r in resp.json()["rooms"]] == ["r101"]

    def test_get_category_404_other_hotel(self, api_client, seeded):
        resp = api_client.get("/categories/std", params={"hotel_id": "otra"})
        assert resp.status_code == 404

    def test_category_rooms(self, api_client, seeded):
        resp = api_client.get("/categories/std/rooms", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        assert [r["id"] for r in resp.json()] == ["r101"]


class TestReservations:
    """ReservationResponse anida guest, room (con su category), services y payments."""

    def test_list_reservations_nested(self, api_client, seeded):
        resp = api_client.get("/reservations", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["id"] == "res1"
        assert item["guest"]["full_name"] == "John Q Doe"
        assert item["room"]["id"] == "r101"
        assert item["room"]["category"]["id"] == "std"
        assert item["services"] == []
        assert item["payments"] == []

    def test_get_reservation_nested(self, api_client, seeded):
        resp = api_client.get("/reservations/res1", params={"hotel_id": HOTEL})
        assert resp.status_code == 200, resp.text
        item = resp.json()
        assert item["room"]["category"]["name"] == "Standard"
        assert item["guest"]["email"] == "john@example.com"

    def test_list_reservations_filters(self, api_client, seeded):
        resp = api_client.get(
            "/reservations", params={"hotel_id": HOTEL, "status": 1}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 0

    def test_get_reservation_404(self, api_client, seeded):
        resp = api_client.get("/reservations/nope", params={"hotel_id": HOTEL})
        assert resp.status_code == 404