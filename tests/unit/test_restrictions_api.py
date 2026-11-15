"""
Tests de `GET /restrictions` (Tarea 2.1).

Esta ruta **no lee de la base de datos**: pega contra la rejilla de OtelMS en
cada llamada, porque las restricciones cambian a menudo desde recepción y una
tabla guardaría una foto congelada. El scraping va monkeypatcheado aquí; lo que
se comprueba es el contrato del endpoint, y el parseo de la rejilla ya está
cubierto en `test_restrictions_scrape.py`.
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from otelms.api import dependencies as deps
from otelms.api.main import app
from otelms.api.routes import restrictions as restrictions_route
from otelms.domain.repositories import CategoryRepository, HotelRepository
from otelms.utils.cache import cache


@pytest_asyncio.fixture(autouse=True)
async def _clear_restrictions_cache_and_rate_limit():
    deps._live_rate_windows.pop("restrictions.list", None)
    if cache._backend is not None:
        await cache.clear_pattern("live:restrictions:*")
    yield
    deps._live_rate_windows.pop("restrictions.list", None)
    if cache._backend is not None:
        await cache.clear_pattern("live:restrictions:*")


@pytest.fixture
def closed_cells():
    """Lo que devolvería el scraper: dos celdas cerradas de Overbooking."""
    return [
        {"category_id": "21", "rate_id": "1", "day_id": "20776",
         "date": "2026-11-19", "closed": True},
        {"category_id": "21", "rate_id": "1", "day_id": "20775",
         "date": "2026-11-18", "closed": True},
    ]


@pytest.fixture
def fake_scrape(monkeypatch, closed_cells):
    """Sustituye el scrapeo por una lista fija y anota los argumentos."""
    calls = []

    async def _fake(hotel_id, **kwargs):
        calls.append({"hotel_id": hotel_id, **kwargs})
        return list(closed_cells)

    monkeypatch.setattr(restrictions_route, "get_restrictions", _fake)
    return calls


@pytest_asyncio.fixture
async def seeded(test_session):
    """Dos categorías con el mismo id que usa OtelMS, para que los nombres
    salgan de la base y no del mapeo de respaldo del portal."""
    hotels = HotelRepository(test_session)
    categories = CategoryRepository(test_session)
    await hotels.create(
        id="18330", name="Hotel 18330", domain="otelms.com",
        username="u@u.com", password_hash="h",
    )
    await categories.create(id="21", hotel_id="18330", name="Overbooking")
    await categories.create(id="13", hotel_id="18330", name="Matrimonial")
    return "18330"


@pytest.fixture
def api_client(test_session):
    old = dict(app.dependency_overrides)
    app.dependency_overrides[deps.verify_api_key] = lambda: None
    app.dependency_overrides[deps.get_category_repo] = (
        lambda: CategoryRepository(test_session)
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


class TestListRestrictions:
    def test_devuelve_las_celdas_cerradas(self, api_client, seeded, fake_scrape):
        resp = api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        # El fixture llega al revés a propósito: el orden lo pone el HTML de la
        # rejilla y no puede ser parte del contrato del endpoint.
        assert [i["date"] for i in body["items"]] == ["2026-11-18", "2026-11-19"]
        assert all(i["closed"] for i in body["items"])

    def test_resuelve_el_nombre_desde_la_base(self, api_client, seeded, fake_scrape):
        resp = api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        assert resp.json()["items"][0]["category_name"] == "Overbooking"

    def test_declara_que_es_una_lectura_en_vivo(self, api_client, seeded, fake_scrape):
        resp = api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        # Sin esto un cliente no distinguiría un dato cacheado de uno actual.
        assert "restrict_calendar" in resp.json()["source"]

    def test_pasa_el_rango_al_scraper(self, api_client, seeded, fake_scrape):
        api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        assert fake_scrape[0]["date_from"] is not None
        assert fake_scrape[0]["rate_id"] == "1"

    def test_filtra_por_categoria(self, api_client, seeded, fake_scrape):
        api_client.get(
            "/restrictions?hotel_id=18330&category_id=13"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        assert fake_scrape[0]["category_ids"] == ["13"]

    def test_sin_filtro_no_limita_categorias(self, api_client, seeded, fake_scrape):
        api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        assert fake_scrape[0]["category_ids"] is None

    def test_rango_invertido_da_400(self, api_client, seeded, fake_scrape):
        resp = api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-19&date_to=2026-11-18"
        )
        assert resp.status_code == 400
        # No debe haber pegado contra el portal para luego decir que no.
        assert fake_scrape == []

    def test_sin_celdas_cerradas_devuelve_lista_vacia(self, api_client, seeded,
                                                       monkeypatch):
        async def _none(hotel_id, **kwargs):
            return []

        monkeypatch.setattr(restrictions_route, "get_restrictions", _none)
        resp = api_client.get(
            "/restrictions?hotel_id=18330"
            "&date_from=2026-11-18&date_to=2026-11-19"
        )
        # Vacío significa "todo abierto en el rango", no "sin datos".
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["items"] == []

    def test_exige_api_key(self, api_client, seeded, fake_scrape):
        old = dict(app.dependency_overrides)
        app.dependency_overrides.pop(deps.verify_api_key, None)
        try:
            resp = api_client.get("/restrictions?hotel_id=18330")
            # Sin header, FastAPI valida antes de llegar a la dependencia (422);
            # con un header que no existe en la tabla, 401. Ninguno de los dos
            # deja pasar la petición.
            assert resp.status_code in (401, 422)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)