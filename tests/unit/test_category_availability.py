"""
Tests de la disponibilidad por categoría (Tarea 1.1).

Cubre las dos capas que el sync sigue usando: el parser de la fila resumen
del calendario (`div.calendar_sum`) y el repositorio que la persiste en
`category_availability`. El endpoint `GET /categories/availability` fue
retirado; esa información ahora se expone vía /rooms/available-for-sale.

El dato clave del módulo: `available` es el número que publica OtelMS, NO
`total - ocupadas`. Contrastado contra el portal, difieren 163 de 414 celdas
(la categoría 13 tiene 12 habitaciones y nunca pasa de 10; hay días con 0
disponibles y solo 5 ocupadas). Ver tests/manual/test_calendar_availability.py.
"""
from datetime import date

import pytest
import pytest_asyncio

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
    """Hotel con 2 categorías (2 y 1 habitaciones) y disponibilidad de 2 días."""
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
