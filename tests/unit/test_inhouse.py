"""
Tests del endpoint de in-house (Tarea 1.4).

OtelMS no tiene endpoint de in-house: se comprobó el menú entero. El listado se
deriva de las reservas que pernoctan la fecha, y el criterio es el rango de
fechas, NO `status == 2` ("Check in"). Contrastado contra el portal: de 270
reservas, las 22 marcadas "Check in" tienen la salida ya pasada y ninguna
pernocta el día consultado.

Ver `tests/manual/test_inhouse_v1_and_sweep.py` para el barrido que lo-calló.
"""
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from otelms.api import dependencies as deps
from otelms.api.main import app
from otelms.domain.repositories import (
    GuestRepository,
    HotelRepository,
    ReservationRepository,
    RoomRepository,
)

HOY = date(2026, 3, 12)


@pytest.fixture
def api_client(test_session):
    old = dict(app.dependency_overrides)
    app.dependency_overrides[deps.verify_api_key] = lambda: None
    app.dependency_overrides[deps.get_room_repo] = (
        lambda: RoomRepository(test_session)
    )
    app.dependency_overrides[deps.get_reservation_repo] = (
        lambda: ReservationRepository(test_session)
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


@pytest_asyncio.fixture
async def seeded(test_session):
    hotels = HotelRepository(test_session)
    guests = GuestRepository(test_session)
    rooms = RoomRepository(test_session)
    reservations = ReservationRepository(test_session)

    await hotels.create(
        id="h1", name="Hotel 1", domain="otelms.com",
        username="u@u.com", password_hash="h",
    )
    await guests.create(id="g1", hotel_id="h1", first_name="Ana", last_name="Ruiz")
    await guests.create(id="g2", hotel_id="h1", first_name="Beto", last_name="Sanz")
    await rooms.create(id="r101", hotel_id="h1", name="101")
    await rooms.create(id="r102", hotel_id="h1", name="102")

    def _dt(d: int, h: int = 14) -> datetime:
        return datetime(2026, 3, d, h, 0, tzinfo=UTC)

    # Pernocta: 3 noches (10 -> 13), status 2 = "Check in" en OtelMS.
    await reservations.create(
        id="res_dentro", hotel_id="h1", room_id="r101", guest_id="g1",
        check_in=_dt(10), check_out=_dt(13, 11), status=2, adults=2,
        total_price="120.00", source="Directa",
    )
    # Llega mañana: no pernocta hoy aunque ya tenga status 1.
    await reservations.create(
        id="res_manana", hotel_id="h1", room_id="r102", guest_id="g2",
        check_in=_dt(13), check_out=_dt(15, 11), status=1,
    )
    # Ya salió: status 2 ("Check in") pero check_out pasada. Es la trampa.
    await reservations.create(
        id="res_stale", hotel_id="h1", room_id="r102", guest_id="g2",
        check_in=_dt(1), check_out=_dt(5, 11), status=2,
    )
    # Cancelada dentro del rango: no cuenta como in-house.
    await reservations.create(
        id="res_cancelada", hotel_id="h1", room_id="r101", guest_id="g2",
        check_in=_dt(11), check_out=_dt(14, 11), status=4,
    )
    return "h1"


def _get(api_client, **params):
    return api_client.get("/reservations/in-house", params={"hotel_id": "h1", **params})


class TestInHouse:
    def test_solo_las_que_pernoctan(self, api_client, seeded):
        body = _get(api_client, target_date="2026-03-12").json()
        assert body["in_house_count"] == 1
        assert body["items"][0]["reservation_id"] == "res_dentro"

    def test_excluye_reserva_stale_check_in(self, api_client, seeded):
        """status 2 con salida pasada no es in-house: es el caso que rompe."""
        ids = {i["reservation_id"] for i in _get(api_client, target_date="2026-03-12").json()["items"]}
        assert "res_stale" not in ids

    def test_excluye_cancelada(self, api_client, seeded):
        ids = {i["reservation_id"] for i in _get(api_client, target_date="2026-03-12").json()["items"]}
        assert "res_cancelada" not in ids

    def test_el_dia_de_salida_no_cuenta(self, api_client, seeded):
        assert _get(api_client, target_date="2026-03-13").json()["in_house_count"] == 1
        # El 13 sale res_dentro y entra res_manana: una noche, no dos.
        ids = {i["reservation_id"] for i in _get(api_client, target_date="2026-03-13").json()["items"]}
        assert ids == {"res_manana"}

    def test_el_dia_de_entrada_si_cuenta(self, api_client, seeded):
        ids = {i["reservation_id"] for i in _get(api_client, target_date="2026-03-10").json()["items"]}
        assert ids == {"res_dentro"}

    def test_dia_sin_huespedes(self, api_client, seeded):
        body = _get(api_client, target_date="2026-04-01").json()
        assert body["in_house_count"] == 0
        assert body["items"] == []
        assert body["occupied_rooms"] == 0

    def test_cuenta_noches(self, api_client, seeded):
        item = _get(api_client, target_date="2026-03-12").json()["items"][0]
        assert item["nights"] == 3        # 10 -> 13
        assert item["nights_elapsed"] == 2  # ya van dos noches (10 y 11)
        assert item["nights_remaining"] == 1

    def test_trae_huesped_y_habitacion(self, api_client, seeded):
        item = _get(api_client, target_date="2026-03-12").json()["items"][0]
        assert item["guest_name"] == "Ana Ruiz"
        assert item["room"]["id"] == "r101"
        assert item["adults"] == 2
        assert item["status"] == 2
        assert item["source"] == "Directa"
        assert str(item["total_price"]) == "120.00"

    async def test_habitaciones_ocupadas_es_distinto_de_huespedes(
        self, api_client, seeded, test_session
    ):
        """Dos reservas en la misma habitación: 2 huéspedes, 1 habitación."""
        await ReservationRepository(test_session).create(
            id="res_compartida", hotel_id="h1", room_id="r101", guest_id="g2",
            check_in=datetime(2026, 3, 12, 14, 0, tzinfo=UTC),
            check_out=datetime(2026, 3, 13, 11, 0, tzinfo=UTC),
            status=2,
        )

        body = _get(api_client, target_date="2026-03-12").json()
        assert body["in_house_count"] == 2
        assert body["occupied_rooms"] == 1

    def test_fecha_por_defecto_es_hoy(self, api_client, seeded):
        body = _get(api_client).json()
        assert body["date"] == date.today().isoformat()

    def test_hotel_sin_reservas(self, api_client, seeded):
        resp = api_client.get("/reservations/in-house", params={"hotel_id": "otro"})
        assert resp.status_code == 200
        assert resp.json()["in_house_count"] == 0

    def test_requiere_hotel_id(self, api_client):
        assert api_client.get("/reservations/in-house").status_code == 422

    def test_no_serve_sin_api_key(self, test_session):
        old = dict(app.dependency_overrides)
        app.dependency_overrides.pop(deps.verify_api_key, None)
        app.dependency_overrides[deps.get_room_repo] = (
            lambda: RoomRepository(test_session)
        )
        app.dependency_overrides[deps.get_reservation_repo] = (
            lambda: ReservationRepository(test_session)
        )
        try:
            resp = TestClient(app).get("/reservations/in-house")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)
        assert resp.status_code in (401, 422)

    def test_no_rompe_reservation_por_id(self, api_client, seeded):
        """/reservations/{id} sigue contestando: in-house va declarado antes."""
        resp = api_client.get(
            "/reservations/res_dentro", params={"hotel_id": "h1"}
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "res_dentro"

    def test_no_rompe_checkins_ni_checkouts(self, api_client, seeded):
        assert api_client.get(
            "/reservations/today/checkins", params={"hotel_id": "h1"}
        ).status_code == 200
        assert api_client.get(
            "/reservations/today/checkouts", params={"hotel_id": "h1"}
        ).status_code == 200