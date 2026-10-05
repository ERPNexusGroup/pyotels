"""
Tests de la disponibilidad por categoría (Tarea 1.1).

Cubre las tres capas: el parser de la fila resumen del calendario
(`div.calendar_sum`), el repositorio que la persiste, y el endpoint
`GET /categories/availability`.

El dato clave del módulo: `available` es el número que publica OtelMS, NO
`total - ocupadas`. Contrastado contra el portal, difieren 163 de 414 celdas
(la categoría 13 tiene 12 habitaciones y nunca pasa de 10; hay días con 0
disponibles y solo 5 ocupadas). Ver tests/manual/test_calendar_availability.py.
"""
from datetime import date

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from otelms.api import dependencies as deps
from otelms.api.main import app
from otelms.domain.repositories import (
    CategoryAvailabilityRepository,
    CategoryRepository,
    HotelRepository,
    RoomRepository,
)
from otelms.scraping.calendar_markup_v2 import parse_availability_v2, parse_grid_v2


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def session(test_session):
    """Alias de la sesión compartida: los tests del repositorio ven lo que
    siembra `seeded`, que escribe en esa misma sesión."""
    return test_session


@pytest_asyncio.fixture
async def seeded(test_session):
    """Hotel con 2 categorías (2 y 1 habitaciones) y disponibilidad de 2 días.

    Usa `test_session` (la sesión que inyecta el TestClient), no una propia:
    si se siembran con otra sesión las filas no existen para el endpoint.
    """
    hotels = HotelRepository(test_session)
    categories = CategoryRepository(test_session)
    rooms = RoomRepository(test_session)

    await hotels.create(
        id="h1", name="Hotel 1", domain="otelms.com",
        username="u@u.com", password_hash="h",
    )
    await categories.create(id="c13", hotel_id="h1", name="Matrimonial")
    await categories.create(id="c14", hotel_id="h1", name="Doble Individual")
    await rooms.create(id="r101", hotel_id="h1", category_id="c13", name="101")
    await rooms.create(id="r102", hotel_id="h1", category_id="c13", name="102")
    await rooms.create(id="r201", hotel_id="h1", category_id="c14", name="201")

    availability = CategoryAvailabilityRepository(test_session)
    await availability.replace("h1", [
        {"category_id": "c13", "date": "2026-10-05", "available": 8},
        {"category_id": "c13", "date": "2026-10-06", "available": 0},
        {"category_id": "c14", "date": "2026-10-05", "available": 1},
        {"category_id": "c14", "date": "2026-10-06", "available": 1},
    ])
    return "h1"


@pytest.fixture
def api_client(test_session):
    old = dict(app.dependency_overrides)
    app.dependency_overrides[deps.verify_api_key] = lambda: None
    app.dependency_overrides[deps.get_category_repo] = (
        lambda: CategoryRepository(test_session)
    )
    app.dependency_overrides[deps.get_availability_repo] = (
        lambda: CategoryAvailabilityRepository(test_session)
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


# ============================================================
# Parser
# ============================================================
DAY = 20731  # 2026-10-05


def _summary_row(category_id: str, day_id: int, value: str) -> str:
    """Celda de la fila resumen: room_id=0 + category_id + div.calendar_sum."""
    return (
        f'<td category_id="{category_id}" class="calendar_td" '
        f'day_id="{day_id}" room_id="0">'
        f'<div class="calendar_sum" id="availability_{category_id}_{day_id}">{value}</div>'
        f"</td>"
    )


def _calendar_html(*bodies: str) -> str:
    return (
        '<table class="calendar_table">'
        + "".join(f"<tbody>{b}</tbody>" for b in bodies)
        + "</table>"
    )


class TestParseAvailability:
    def test_lee_numero_y_fecha(self):
        html = _calendar_html(
            f'<tr class="calendar_tr">{_summary_row("13", DAY, "8")}</tr>'
        )
        assert parse_availability_v2(html) == [
            {"category_id": "13", "date": "2026-10-05", "available": 8}
        ]

    def test_cero_es_un_numero_valido(self):
        """Un 0 es 'no hay nada disponible', no un hueco: se conserva."""
        html = _calendar_html(
            f'<tr class="calendar_tr">{_summary_row("13", DAY, "0")}</tr>'
        )
        assert parse_availability_v2(html)[0]["available"] == 0

    def test_ignora_las_filas_de_habitacion(self):
        """Las celdas ocupadas tienen room_id real: no son disponibilidad."""
        html = _calendar_html(
            f'<tr class="calendar_tr btn_close_box13">'
            f'<td room_id="101" class="calendar_td" day_id="{DAY}">'
            f'<div class="calendar_item" resid="23356"></div></td></tr>'
        )
        assert parse_availability_v2(html) == []

    def test_no_descarta_valores_no_numericos(self):
        """Un '-', 'N/A' o vacío no son 0: si no hay número, no hay fila."""
        html = _calendar_html(
            f'<tr class="calendar_tr">{_summary_row("13", DAY, "N/A")}</tr>'
        )
        assert parse_availability_v2(html) == []

    def test_sin_tabla(self):
        assert parse_availability_v2("<div>no hay calendario</div>") == []

    def test_una_fila_por_categoria_y_dia(self):
        html = _calendar_html(
            f'<tr class="calendar_tr">{_summary_row("13", DAY, "8")}'
            f'{_summary_row("13", DAY + 1, "10")}</tr>',
            f'<tr class="calendar_tr">{_summary_row("14", DAY, "4")}</tr>',
        )
        rows = parse_availability_v2(html)
        assert len(rows) == 3
        assert {(r["category_id"], r["available"]) for r in rows} == {
            ("13", 8), ("13", 10), ("14", 4),
        }

    def test_parse_grid_lo_incluye(self):
        """parse_grid tiene que devolverlo: es lo que consume el sync."""
        html = _calendar_html(
            f'<tr class="calendar_tr">{_summary_row("13", DAY, "8")}</tr>'
        )
        assert parse_grid_v2(html)["availability"] == [
            {"category_id": "13", "date": "2026-10-05", "available": 8}
        ]

    def test_parse_grid_sin_disponibilidad_devuelve_lista_vacia(self):
        grid = parse_grid_v2(_calendar_html('<tr class="calendar_tr"><td>x</td></tr>'))
        assert grid["availability"] == []


# ============================================================
# Repositorio
# ============================================================
class TestAvailabilityRepository:
    async def test_persiste_las_filas(self, session):
        repo = CategoryAvailabilityRepository(session)
        await HotelRepository(session).create(
            id="h2", name="H2", domain="otelms.com",
            username="u", password_hash="h",
        )
        await CategoryRepository(session).create(id="cx", hotel_id="h2", name="X")

        n = await repo.replace("h2", [
            {"category_id": "cx", "date": "2026-10-05", "available": 5}
        ])
        assert n == 1

        rows = await repo.get_range("h2", date(2026, 10, 1), date(2026, 10, 31))
        assert [(r.category_id, r.date.isoformat(), r.available) for r in rows] == [
            ("cx", "2026-10-05", 5)
        ]

    async def test_replace_borra_lo_anterior_de_esa_categoria(self, session, seeded):
        """Un sync sustituye la ventana completa: lo que no vuelve, se va."""
        repo = CategoryAvailabilityRepository(session)
        await repo.replace("h1", [
            {"category_id": "c13", "date": "2026-10-07", "available": 3},
        ])

        rows = await repo.get_range("h1", date(2026, 10, 1), date(2026, 10, 31))
        # c13 se queda solo con el 07; c14 no se tocó.
        assert {(r.category_id, r.date.isoformat()) for r in rows} == {
            ("c13", "2026-10-07"), ("c14", "2026-10-05"), ("c14", "2026-10-06"),
        }

    async def test_no_toca_otras_categorias(self, session, seeded):
        repo = CategoryAvailabilityRepository(session)
        await repo.replace("h1", [
            {"category_id": "c14", "date": "2026-10-08", "available": 1},
        ])
        rows = await repo.get_range("h1", date(2026, 10, 1), date(2026, 10, 31))
        c13 = [r for r in rows if r.category_id == "c13"]
        assert len(c13) == 2

    async def test_replace_vacio_no_borra(self, session, seeded):
        repo = CategoryAvailabilityRepository(session)
        assert await repo.replace("h1", []) == 0
        rows = await repo.get_range("h1", date(2026, 10, 1), date(2026, 10, 31))
        assert len(rows) == 4

    async def test_filtra_por_categoria(self, session, seeded):
        repo = CategoryAvailabilityRepository(session)
        rows = await repo.get_range(
            "h1", date(2026, 10, 1), date(2026, 10, 31), category_id="c14"
        )
        assert {r.category_id for r in rows} == {"c14"}

    async def test_respeta_los_limites_del_rango(self, session, seeded):
        repo = CategoryAvailabilityRepository(session)
        rows = await repo.get_range("h1", date(2026, 10, 6), date(2026, 10, 6))
        assert {r.date.isoformat() for r in rows} == {"2026-10-06"}

    async def test_isola_hoteles(self, session, seeded):
        repo = CategoryAvailabilityRepository(session)
        rows = await repo.get_range("h9", date(2026, 10, 1), date(2026, 10, 31))
        assert list(rows) == []


# ============================================================
# Endpoint
# ============================================================
class TestAvailabilityEndpoint:
    def test_devuelve_el_rango_pedido(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability",
            params={
                "hotel_id": "h1",
                "date_from": "2026-10-05",
                "date_to": "2026-10-06",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 4
        assert {i["category_id"] for i in body["items"]} == {"c13", "c14"}

    def test_devuelve_el_numero_del_portal(self, api_client, seeded):
        """No recalcula: 8 con 2 habitaciones es lo que dice OtelMS."""
        resp = api_client.get(
            "/categories/availability",
            params={"hotel_id": "h1", "date_from": "2026-10-05", "date_to": "2026-10-05"},
        )
        rows = {(i["category_id"]): i for i in resp.json()["items"]}
        assert rows["c13"]["available"] == 8
        assert rows["c13"]["total_rooms"] == 2
        assert rows["c13"]["category_name"] == "Matrimonial"

    def test_ordena_por_fecha_y_categoria(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability",
            params={"hotel_id": "h1", "date_from": "2026-10-05", "date_to": "2026-10-06"},
        )
        keys = [(i["date"], i["category_id"]) for i in resp.json()["items"]]
        assert keys == sorted(keys)

    def test_filtro_por_categoria(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability",
            params={
                "hotel_id": "h1", "date_from": "2026-10-01",
                "date_to": "2026-10-31", "category_id": "c14",
            },
        )
        assert {i["category_id"] for i in resp.json()["items"]} == {"c14"}

    def test_rango_por_defecto_de_45_dias(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability", params={"hotel_id": "h1"}
        )
        assert resp.status_code == 200
        assert resp.json()["date_to"] > resp.json()["date_from"]

    def test_rango_invertido_da_400(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability",
            params={"hotel_id": "h1", "date_from": "2026-10-06", "date_to": "2026-10-05"},
        )
        assert resp.status_code == 400

    def test_hotel_sin_datos_devuelve_lista_vacia(self, api_client, seeded):
        resp = api_client.get(
            "/categories/availability", params={"hotel_id": "no-existe"}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "hotel_id": "no-existe",
            "date_from": resp.json()["date_from"],
            "date_to": resp.json()["date_to"],
            "count": 0,
            "items": [],
        }

    def test_requiere_hotel_id(self, api_client):
        assert api_client.get("/categories/availability").status_code == 422

    def test_no_serve_sin_api_key(self, test_session):
        old = dict(app.dependency_overrides)
        app.dependency_overrides.pop(deps.verify_api_key, None)
        app.dependency_overrides[deps.get_availability_repo] = (
            lambda: CategoryAvailabilityRepository(test_session)
        )
        app.dependency_overrides[deps.get_category_repo] = (
            lambda: CategoryRepository(test_session)
        )
        try:
            resp = TestClient(app).get("/categories/availability")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)
        assert resp.status_code in (401, 422)

    def test_no_rompe_las_rutas_vecinas(self, api_client, seeded):
        """/categories/{id} y /categories/{id}/rooms siguen contestando."""
        assert api_client.get("/categories", params={"hotel_id": "h1"}).status_code == 200
        assert api_client.get(
            "/categories/c13", params={"hotel_id": "h1"}
        ).status_code == 200
        assert api_client.get(
            "/categories/c13/rooms", params={"hotel_id": "h1"}
        ).status_code == 200