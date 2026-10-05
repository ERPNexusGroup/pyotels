"""Cierre/apertura de fechas contra OtelMS.

El HTML de la rejilla y el del modal están copiados de la captura real de
`tests/manual/restrict_calendar.html` y `restrict_modal.html`, recortados a las
pocas celdas que cada test necesita. El flujo de escritura se comprueba con
`httpx.MockTransport`: los tres POST en orden y el cuerpo exacto de cada uno,
incluido el paso de selección que no se puede saltar.
"""
import asyncio

import httpx
import pytest
from urllib.parse import parse_qs

from otelms.scraping.restrictions import (
    CATEGORY_IDS,
    CLOSED,
    CLOSED_CELL_CLASS,
    DELETE_URL,
    OPEN,
    RATE_HOLIDAYS,
    RATE_STANDARD,
    SAVE_URL,
    SELECT_URL,
    _save_payload,
    _select_payload,
    close_dates,
    get_categories,
    get_restrictions,
    open_dates,
    parse_closed_cells,
    parse_modal_state,
    parse_restriction_cells,
    set_dates_state,
)

# day_id 20731 = 2026-10-05, 20776 = 2026-11-19
GRID = """
<table>
  <tr class="calendar_tr">
    <td category_id="13" class="calendar_td ui-selectee" date="20731" day_id="20731"
        fulldate="2026-10-05" hms_rate_id="1" id="1_20731" rate_id="1"
        title="Standard, 2026-10-05"><div class="current_data3"><span>05</span></div></td>
    <td category_id="13" class="calendar_td ui-selectee" date="20732" day_id="20732"
        fulldate="2026-10-06" hms_rate_id="1" id="1_20732" rate_id="2"
        title="Feriados, 2026-10-06"><div class="current_data3"><span>06</span></div></td>
    <td category_id="21" class="calendar_td ui-selectee bg_padlock calendar_price_change"
        date="20776" day_id="20776" fulldate="2026-11-19" hms_rate_id="1" id="1_20776"
        rate_id="1" title="Standard, 2026-11-19"></td>
    <td category_id="14" class="calendar_td" date="20731" day_id="20731"
        fulldate="2026-10-05" id="0_20731"><div>sin rate_id</div></td>
    <td class="calendar_sum" category_id="0">8</td>
  </tr>
</table>
<select name="categories[]">
  <option value="13">Matrimonial</option>
  <option value="21">Overbooking</option>
</select>
"""

# El modal real marca la opción vigente con selected.
MODAL_OPEN = """
<form id="frmData" action="/reservation_c2/setrestrict_deskpost" method="post">
  <input type="hidden" id="delete_action" name="delete_action" value="0">
  <input type="hidden" name="category_id" value="21">
  <input type="hidden" name="rate_id" value="1">
  <input id="datein" name="datein" value="2026-11-19">
  <input id="dateout" name="dateout" value="2026-11-19">
  <select name="closed">
    <option value="2" selected>No cambiar</option>
    <option value="0">Abierto</option>
    <option value="1">Cerrado</option>
  </select>
</form>
"""

MODAL_CLOSED = MODAL_OPEN.replace(
    '<option value="2" selected>No cambiar</option>',
    '<option value="2">No cambiar</option><option value="1" selected>Cerrado</option>',
)


# ============================================================
# Parsing de la rejilla
# ============================================================
class TestParseCells:
    def test_crea_una_celda_por_td(self):
        cells = parse_restriction_cells(GRID)
        assert len(cells) == 3

    def test_campos_de_la_celda(self):
        first = parse_restriction_cells(GRID)[0]
        assert first == {
            "category_id": "13",
            "rate_id": "1",
            "day_id": "20731",
            "date": "2026-10-05",
            "closed": False,
        }

    def test_bg_padlock_es_celda_cerrada(self):
        by_date = {c["date"]: c for c in parse_restriction_cells(GRID)}
        assert by_date["2026-11-19"]["closed"] is True
        assert by_date["2026-10-05"]["closed"] is False

    def test_descarta_celda_sin_rate_id(self):
        # El td de categoría 14 no lleva rate_id: no es una celda de la rejilla
        # de restricciones, es otro tipo de celda.
        assert {c["category_id"] for c in parse_restriction_cells(GRID)} == {"13", "21"}

    def test_descarta_la_fila_resumen(self):
        # `calendar_sum` no lleva class="calendar_td", así que no entra.
        assert all(c["date"] != "2026-10-05" or c["category_id"] != "0"
                   for c in parse_restriction_cells(GRID))

    def test_filtra_por_categoria(self):
        cells = parse_restriction_cells(GRID, category_ids=["21"])
        assert [c["date"] for c in cells] == ["2026-11-19"]

    def test_filtra_por_tarifa(self):
        cells = parse_restriction_cells(GRID, category_ids=["13"], rate_id=RATE_HOLIDAYS)
        assert [(c["date"], c["rate_id"]) for c in cells] == [("2026-10-06", "2")]

    def test_filtra_por_rango_de_fechas(self):
        cells = parse_restriction_cells(
            GRID, date_from="2026-10-06", date_to="2026-10-06"
        )
        assert [c["date"] for c in cells] == ["2026-10-06"]

    def test_rango_invertido_no_devuelve_nada(self):
        assert parse_restriction_cells(
            GRID, date_from="2026-11-19", date_to="2026-10-05"
        ) == []

    def test_html_vacio_no_revienta(self):
        assert parse_restriction_cells("") == []


class TestParseClosed:
    def test_solo_las_cerradas(self):
        closed = parse_closed_cells(GRID)
        assert len(closed) == 1
        assert closed[0]["category_id"] == "21"

    def test_respeta_los_filtros(self):
        assert parse_closed_cells(GRID, category_ids=["13"]) == []


class TestParseModal:
    def test_lee_el_estado_reflejado(self):
        state = parse_modal_state(MODAL_CLOSED)
        assert state["closed"] == CLOSED
        assert state["category_id"] == "21"
        assert state["datein"] == "2026-11-19"

    def test_abierto_queda_sin_cambiar(self):
        # El modal marca "No cambiar" (2), que no es lo mismo que abierto (0).
        assert parse_modal_state(MODAL_OPEN)["closed"] == "2"

    def test_modal_vacio_no_revienta(self):
        assert parse_modal_state("") == {}


# ============================================================
# Payloads
# ============================================================
class TestPayloads:
    def test_seleccion_usa_el_nombre_con_tres_ses(self):
        cells = parse_restriction_cells(GRID, category_ids=["21"])
        payload = _select_payload(cells)
        assert payload["resstrict_data[0][rate_id]"] == "1"
        assert payload["resstrict_data[0][category_id]"] == "21"
        # `date` es el day_id, `fulldate` la fecha ISO: son dos campos distintos.
        assert payload["resstrict_data[0][date]"] == "20776"
        assert payload["resstrict_data[0][fulldate]"] == "2026-11-19"

    def test_save_incluye_los_siete_dias(self):
        cells = parse_restriction_cells(GRID, category_ids=["21"])
        payload = _save_payload(cells, CLOSED)
        assert payload["week[0]"] == "1" and payload["week[6]"] == "1"
        assert len([k for k in payload if k.startswith("week[")]) == 7

    def test_save_usa_el_rango_de_la_seleccion(self):
        cells = parse_restriction_cells(GRID, category_ids=["13"])
        payload = _save_payload(cells, OPEN)
        assert payload["datein"] == "2026-10-05"
        assert payload["dateout"] == "2026-10-06"

    def test_save_marca_borrado_solo_cuando_se_pide(self):
        cells = parse_restriction_cells(GRID, category_ids=["21"])
        assert _save_payload(cells, CLOSED)["delete_action"] == "0"
        assert _save_payload(cells, CLOSED, delete=True)["delete_action"] == "1"


# ============================================================
# Flujo de escritura
# ============================================================
def _recorder(applied=1, responses=None):
    """MockTransport que anota las peticiones y responde como el portal."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        calls.append({"method": request.method, "url": str(request.url),
                      "body": body,
                      # httpx URL-encorea las claves con corchetes, así que las
                      # aserciones leen el body decodificado.
                      "form": {k: v[0] for k, v in parse_qs(body).items()}})
        if request.url.path == SELECT_URL:
            return httpx.Response(200, text=MODAL_OPEN)
        if request.url.path in (SAVE_URL, DELETE_URL):
            if responses is not None:
                return httpx.Response(200, json=responses)
            return httpx.Response(200, json={
                "ok": 1, "count_restricts_data": applied,
                "intdatein": 20776, "intdateout": 20776,
                "category_id": "21", "rate_id": "1", "restricts_data": {},
            })
        return httpx.Response(200, text=GRID)

    return calls, httpx.MockTransport(handler)


@pytest.fixture
def cells():
    return parse_restriction_cells(GRID, category_ids=["21"])


class TestSetDatesState:
    async def test_selecciona_antes_de_guardar(self, cells):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            await set_dates_state("18330", cells, CLOSED, client=client)
        assert [c["url"].split("/x")[1] for c in calls] == [SELECT_URL, SAVE_URL]

    async def test_envia_el_flag_de_cerrar(self, cells):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            await set_dates_state("18330", cells, CLOSED, client=client)
        assert calls[1]["form"]["closed"] == "1"

    async def test_abrir_envia_el_flag_de_abrir(self, cells):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            await set_dates_state("18330", cells, OPEN, client=client)
        assert calls[1]["form"]["closed"] == "0"

    async def test_devuelve_el_json_del_portal(self, cells):
        _, transport = _recorder(applied=1)
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            result = await set_dates_state("18330", cells, CLOSED, client=client)
        assert result["count_restricts_data"] == 1
        assert result["requested_cells"] == 1

    async def test_avisa_si_el_portal_no_aplico_nada(self, cells, caplog):
        # ok=1 con count 0 es el síntoma de saltarse el paso de selección.
        _, transport = _recorder(applied=0)
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            with caplog.at_level("WARNING"):
                result = await set_dates_state("18330", cells, CLOSED, client=client)
        assert result["count_restricts_data"] == 0
        assert "applied 0 days" in caplog.text

    async def test_falla_si_el_portal_responde_mal(self, cells):
        def handler(request):
            if request.url.path == SELECT_URL:
                return httpx.Response(200, text=MODAL_OPEN)
            return httpx.Response(200, json={"ok": 0})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://x"
        ) as client:
            with pytest.raises(RuntimeError, match="Save failed"):
                await set_dates_state("18330", cells, CLOSED, client=client)

    async def test_sin_celdas_no_llama_al_portal(self):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            with pytest.raises(ValueError):
                await set_dates_state("18330", [], CLOSED, client=client)
        assert calls == []

    async def test_rechaza_mezclar_categorias(self):
        cells = parse_restriction_cells(GRID, category_ids=["13", "21"])
        _, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            with pytest.raises(ValueError, match="misma categoría"):
                await set_dates_state("18330", cells, CLOSED, client=client)

    async def test_rechaza_mezclar_tarifas(self):
        cells = parse_restriction_cells(GRID, category_ids=["13"])
        _, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            with pytest.raises(ValueError, match="misma categoría"):
                await set_dates_state("18330", cells, CLOSED, client=client)


class TestRangeHelpers:
    async def test_cerrar_un_rango_agrupa_por_categoria(self):
        calls, transport = _recorder(applied=2)
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            result = await close_dates(
                "18330", "2026-10-05", "2026-10-06",
                categories=["Matrimonial", "Doble Individual"], client=client,
            )
        # Primero se lee la rejilla para traducir el rango a celdas. En ese
        # rango sólo hay categoría 13, así que una sola llamada (select + save);
        # la categoría 14 pedida no aparece y se avisa por log, no se inventa.
        assert [c["url"].split("/x")[1] for c in calls] == [
            "/reservation_c2/restrict_calendar", SELECT_URL, SAVE_URL,
        ]
        assert result["by_category"]["Matrimonial"]["count_restricts_data"] == 2
        assert "Doble Individual" not in result["by_category"]

    async def test_rango_sin_celdas_no_escribe(self):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            result = await close_dates(
                "18330", "2027-06-01", "2027-06-02",
                categories=["Matrimonial"], client=client,
            )
        assert [c["url"].split("/x")[1] for c in calls] == ["/reservation_c2/restrict_calendar"]
        assert result["count_restricts_data"] == 0
        assert "Matrimonial" not in result["by_category"]

    async def test_abrir_usa_closed_0(self):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            await open_dates(
                "18330", "2026-11-19", "2026-11-19",
                categories=["Overbooking"], client=client,
            )
        assert calls[-1]["form"]["closed"] == "0"

    async def test_tarifa_de_feriados_se_pide_explicita(self):
        calls, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            await open_dates(
                "18330", "2026-10-06", "2026-10-06",
                categories=["Matrimonial"], rate_id=RATE_HOLIDAYS, client=client,
            )
        assert calls[1]["form"]["resstrict_data[0][rate_id]"] == "2"


class TestReads:
    async def test_get_restrictions_devuelve_las_cerradas(self):
        _, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            closed = await get_restrictions("18330", client=client)
        assert [c["category_id"] for c in closed] == ["21"]

    async def test_get_categories_lee_el_select(self):
        _, transport = _recorder()
        async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
            cats = await get_categories("18330", client=client)
        assert cats == ["Matrimonial", "Overbooking"]

    async def test_get_categories_sin_select_devuelve_vacio(self):
        def handler(request):
            return httpx.Response(200, text="<html><body>nada</body></html>")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://x"
        ) as client:
            assert await get_categories("18330", client=client) == []


def test_categoria_desconocida_falla_antes_de_llamar_al_portal():
    calls, transport = _recorder()
    client = httpx.AsyncClient(transport=transport, base_url="https://x")
    with pytest.raises(KeyError):
        asyncio.run(close_dates(
            "18330", "2026-10-05", "2026-10-06",
            categories=["NoExiste"], client=client,
        ))
    assert calls == []


def test_tarifa_standard_es_el_defecto():
    assert RATE_STANDARD == "1"
    assert RATE_HOLIDAYS == "2"
    assert CLOSED_CELL_CLASS == "bg_padlock"


def test_las_nueve_categorias_siguen_mapeadas():
    # El portal expone 9; si una desaparece, el mapeo hardcodeado miente.
    assert len(CATEGORY_IDS) == 9
    assert CATEGORY_IDS["Overbooking"] == "21"