"""
Tests del cliente de check-in / check-out / movimiento (Fase 2).

El HTML de los fixtures es la forma real que devuelve `/master_c2/step_1`
y `/master_c2/checkout_step_1`, recortada a los campos que el parser mira.
El portal **no** se llama en ningún test: las tres operaciones se ejercitan
con `MockTransport`.

Lo que se fija aquí, por orden de importancia:

1. Que `move_reservation` **no inventa precios**: los `day_price` del portal
   viajan intactos aunque cambien las fechas.
2. Que el check-out de una reserva que no ha llegado no se reenvía (daría una
   estancia de duración negativa).
3. Que la URL de cada operación es la que se leyó del HTML.
"""
from datetime import date
from urllib.parse import parse_qs

import httpx
import pytest

from otelms.scraping.checkin import (
    BASE,
    CHECKIN_URL,
    CHECKOUT_URL,
    LANDING_CHECKIN,
    LANDING_CHECKOUT,
    UPDATE_RESERVATION_URL,
    check_in,
    check_out,
    get_reservation_form,
    move_reservation,
    parse_reservation_form,
    parse_reservation_summary,
    summarise,
)

# --- HTML real, recortado -------------------------------------------------
# Estructura tomada de la respuesta del portal. `day_price` aparece una vez
# por noche y el `room_id` sale dos veces (hidden con la actual + select), que
# es lo que hace el form de verdad.
FORM_CHECKIN = """
<html><body>
<form action="/reservation_c2/update_reservation" method="post" id="frmdata_modal">
  <input type="hidden" name="reservation_id" value="23565">
  <input type="hidden" name="insert_or_update_guest_id" value="0">
  <input type="hidden" name="room_id" value="109">
  <input type="hidden" name="landing_page" value="master_checkin">
  <input name="datein" value="2026-10-09">
  <select name="checkintime">
    <option value="00:00">00:00</option>
    <option value="14:00" selected>14:00</option>
  </select>
  <input name="duration" value="2">
  <input name="dateout" value="2026-10-11">
  <select name="checkouttime"><option value="12:00" selected>12:00</option></select>
  <input type="checkbox" name="early_check_in" value="1">
  <input type="checkbox" name="late_check_out" value="1" checked>
  <select name="category">
    <option value="13" selected>Matrimonial</option>
    <option value="14">Doble Individual</option>
  </select>
  <select name="room_id"><option value="109" selected>203</option></select>
  <select name="adults"><option value="1" selected>1</option></select>
  <select name="price_type"><option value="46" selected>Directa (2 Pax)</option></select>
  <select name="percent_discount"><option value="0" selected>---</option></select>
  <input name="discount" value="4">
  <input name="service_main_amount" value="46.00">
  <input name="day_price[20735]" value="23.00">
  <input name="day_price[20736]" value="23.00">
  <button name="cancelar" type="button">Cancelar</button>
</form>
</body></html>
"""

# Mismo caso pero del checkout y con la reserva sin llegar: `dateout` cae en
# hoy y `duration` sale negativo. Es el caso que hay que refuse.
FORM_CHECKOUT_NOT_ARRIVED = FORM_CHECKIN.replace(
    '<input type="hidden" name="landing_page" value="master_checkin">',
    '<input type="hidden" name="landing_page" value="master_checkout">',
).replace(
    '<input name="dateout" value="2026-10-11">',
    '<input type="hidden" name="dateout" value="2026-10-05">',
).replace(
    '<input name="duration" value="2">',
    '<input type="hidden" name="duration" value="-4">',
)

# Checkout de una reserva que sí está dentro (medido sobre 23356): fechas
# coherentes y duración positiva. Es el caso normal de un check-out.
FORM_CHECKOUT_ARRIVED = FORM_CHECKIN.replace(
    '<input type="hidden" name="landing_page" value="master_checkin">',
    '<input type="hidden" name="landing_page" value="master_checkout">',
).replace(
    '<input name="datein" value="2026-10-09">',
    '<input type="hidden" name="datein" value="2026-09-20">',
).replace(
    '<input name="duration" value="2">',
    '<input type="hidden" name="duration" value="15">',
)


def _client(handler):
    """Cliente con MockTransport, que es lo que evita tocar el portal."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _recorder(pages=None, responses=None):
    """Devuelve (calls, handler). `pages` mapea url-sufijo → html."""
    calls: list[dict] = []
    pages = pages or {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            body = parse_qs(request.content.decode())
        calls.append({
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "form": body,
        })
        for suffix, html in pages.items():
            if request.url.path.endswith(suffix) or suffix in request.url.path:
                return httpx.Response(200, text=html)
        status, text = (responses or {}).get(request.url.path, (200, ""))
        return httpx.Response(status, text=text)

    return calls, handler


class TestParseForm:
    def test_lee_los_campos_clave(self):
        form = parse_reservation_form(FORM_CHECKIN)
        assert form["reservation_id"] == "23565"
        assert form["datein"] == "2026-10-09"
        assert form["dateout"] == "2026-10-11"
        assert form["landing_page"] == LANDING_CHECKIN

    def test_los_select_toman_la_opcion_marcada(self):
        form = parse_reservation_form(FORM_CHECKIN)
        assert form["category"] == "13"
        assert form["price_type"] == "46"

    def test_los_checkbox_sin_marcar_no_se_mandan(self):
        form = parse_reservation_form(FORM_CHECKIN)
        # El navegador no manda un checkbox desmarcado.
        assert "early_check_in" not in form
        assert form["late_check_out"] == "1"

    def test_conserva_los_day_price_con_su_nombre(self):
        form = parse_reservation_form(FORM_CHECKIN)
        assert form["day_price[20735]"] == "23.00"
        assert form["day_price[20736]"] == "23.00"

    def test_el_room_id_duplicado_gana_el_select(self):
        form = parse_reservation_form(FORM_CHECKIN)
        assert form["room_id"] == "109"

    def test_sin_el_form_lanza_value_error(self):
        with pytest.raises(ValueError, match="update_reservation"):
            parse_reservation_form("<html><body>nada</body></html>")

    def test_resumen_solo_trae_la_identidad(self):
        resumen = parse_reservation_summary(FORM_CHECKIN)
        assert set(resumen) == {
            "reservation_id", "room_id", "category", "datein", "dateout",
            "duration", "adults", "landing_page",
        }
        assert "day_price[20735]" not in resumen

    def test_resumen_de_una_reserva_sin_llegar(self):
        resumen = parse_reservation_summary(FORM_CHECKOUT_NOT_ARRIVED)
        # Lo que el portal devuelve de verdad: duración negativa.
        assert resumen["duration"] == "-4"
        assert resumen["landing_page"] == LANDING_CHECKOUT


class TestReads:
    async def test_lee_el_asistente_de_checkin(self):
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            form = await get_reservation_form("18330", "23565", client=c)
        assert calls[0]["method"] == "GET"
        assert calls[0]["path"].endswith("/step_1/23565/")
        assert form["reservation_id"] == "23565"

    async def test_lee_el_asistente_de_checkout(self):
        calls, handler = _recorder(pages={"checkout_step_1": FORM_CHECKOUT_NOT_ARRIVED})
        async with _client(handler) as c:
            form = await get_reservation_form(
                "18330", "23565", checkout=True, client=c,
            )
        assert calls[0]["path"].endswith("/checkout_step_1/23565")
        assert form["landing_page"] == LANDING_CHECKOUT

    async def test_el_cliente_pasado_se_usa_tal_cual(self):
        """Si el caller trae cliente, no se abre otro ni se cierra el suyo."""
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        client = _client(handler)
        await get_reservation_form("18330", "23565", client=client)
        assert len(calls) == 1
        assert not client.is_closed


class TestCheckinCheckout:
    async def test_checkin_pega_a_la_url_leida(self):
        calls, handler = _recorder(responses={})
        async with _client(handler) as c:
            ok = await check_in("18330", "23565", client=c)
        assert ok is True
        assert calls[0]["method"] == "GET"
        assert calls[0]["path"] == "/reservation_c2/set_checkin/23565/status"

    async def test_checkout_pega_a_la_url_leida(self):
        calls, handler = _recorder(responses={})
        async with _client(handler) as c:
            ok = await check_out("18330", "23565", client=c)
        assert ok is True
        assert calls[0]["path"] == "/reservation_c2/set_checkout/23565/status"

    async def test_una_url_que_falla_no_da_ok(self):
        calls, handler = _recorder(
            responses={"/reservation_c2/set_checkin/23565/status": (500, "")},
        )
        async with _client(handler) as c:
            ok = await check_in("18330", "23565", client=c)
        assert ok is False

    def test_las_urls_son_las_del_html(self):
        # Fijado a mano a propósito: si cambia el portal, este test salta.
        assert CHECKIN_URL.format(resid="7") == "/reservation_c2/set_checkin/7/status"
        assert CHECKOUT_URL.format(resid="7") == "/reservation_c2/set_checkout/7/status"


class TestMove:
    async def test_exige_al_menos_un_cambio(self):
        _, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            with pytest.raises(ValueError, match="Hay que cambiar algo"):
                await move_reservation("18330", "23565", client=c)

    async def test_cambia_de_habitacion(self):
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            await move_reservation("18330", "23565", room_id="110", client=c)
        posted = [x for x in calls if x["method"] == "POST"][0]
        assert posted["path"] == UPDATE_RESERVATION_URL
        assert posted["form"]["room_id"] == ["110"]
        assert posted["form"]["reservation_id"] == ["23565"]

    async def test_no_inventa_precios_al_mover_de_habitacion(self):
        """El motivo de que este módulo relea el form en vez de armarlo."""
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            await move_reservation("18330", "23565", room_id="110", client=c)
        form = [x for x in calls if x["method"] == "POST"][0]["form"]
        assert form["day_price[20735]"] == ["23.00"]
        assert form["service_main_amount"] == ["46.00"]

    async def test_recalcula_la_duracion_al_mover_de_fechas(self):
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            await move_reservation(
                "18330", "23565",
                date_in=date(2026, 10, 9), date_out=date(2026, 10, 14),
                client=c,
            )
        form = [x for x in calls if x["method"] == "POST"][0]["form"]
        assert form["dateout"] == ["2026-10-14"]
        assert form["duration"] == ["5"]

    async def test_no_toca_los_campos_no_pedidos(self):
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            await move_reservation("18330", "23565", category_id="14", client=c)
        form = [x for x in calls if x["method"] == "POST"][0]["form"]
        assert form["category"] == ["14"]
        assert form["room_id"] == ["109"]      # intacto
        assert form["datein"] == ["2026-10-09"]  # intacto

    async def test_preserva_el_landing_page_del_portal(self):
        calls, handler = _recorder(pages={"checkout_step_1": FORM_CHECKOUT_ARRIVED})
        async with _client(handler) as c:
            await move_reservation(
                "18330", "23356", room_id="110", checkout=True, client=c,
            )
        form = [x for x in calls if x["method"] == "POST"][0]["form"]
        assert form["landing_page"] == [LANDING_CHECKOUT]

    async def test_rechaza_mover_una_reserva_que_no_ha_llegado(self):
        """Reenviar ese form guardaría una estancia de -4 noches."""
        calls, handler = _recorder(pages={"checkout_step_1": FORM_CHECKOUT_NOT_ARRIVED})
        async with _client(handler) as c:
            with pytest.raises(ValueError, match="no ha llegado"):
                await move_reservation(
                    "18330", "23565", room_id="110", checkout=True, client=c,
                )
        assert [x for x in calls if x["method"] == "POST"] == []

    async def test_si_se_fijan_fechas_no_choca_con_el_guard(self):
        calls, handler = _recorder(pages={"checkout_step_1": FORM_CHECKOUT_NOT_ARRIVED})
        async with _client(handler) as c:
            await move_reservation(
                "18330", "23565",
                date_in=date(2026, 10, 9), date_out=date(2026, 10, 11),
                checkout=True, client=c,
            )
        form = [x for x in calls if x["method"] == "POST"][0]["form"]
        assert form["duration"] == ["2"]

    async def test_lee_antes_de_escribir(self):
        """El GET del form tiene que ocurrir antes del POST."""
        calls, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            await move_reservation("18330", "23565", room_id="110", client=c)
        metodos = [x["method"] for x in calls]
        assert metodos == ["GET", "POST"]

    async def test_devuelve_el_form_que_se_envio(self):
        _, handler = _recorder(pages={"step_1": FORM_CHECKIN})
        async with _client(handler) as c:
            form = await move_reservation("18330", "23565", room_id="110", client=c)
        assert form["room_id"] == "110"
        assert summarise(form)["category"] == "13"

    def test_base_es_el_portal_de_produccion(self):
        assert BASE == "https://desktop.otelms.com"
