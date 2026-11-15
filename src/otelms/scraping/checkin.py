"""Check-in, check-out y cambio de habitación contra OtelMS.

Todo lo de aquí está leído del HTML del portal, no deducido. Evidencia en
`tests/manual/test_checkin_wizard.py`, `test_checkin_final_steps.py` y
`test_move_update_reservation.py`; escrito en `docs/otelms_endpoints.md` §4.6.

## Las tres operaciones

**Check-in y check-out** son un enlace verde del `panel-footer` del último
paso del asistente. No hay form, ni token, ni POST:

    GET /reservation_c2/set_checkin/{resid}/status
    GET /reservation_c2/set_checkout/{resid}/status

El `/status` final es un segmento literal de la ruta, no un query param.

**Cambiar habitación o fechas** es otra cosa: el paso 1 de ambos asistentes
postea a `/reservation_c2/update_reservation` con 26-30 campos, y la pestaña
del check-out se titula literalmente "Cambiar las fechas de la estancia". Ese
form es el "mover".

## Por qué `move_reservation` relee el form en vez de construirlo

El form lleva un `day_price[day_id]` por noche, un `service_main_amount`, un
`price_type` y un `percent_discount`. Si las fechas cambian, los `day_id`
deben cambiar con ellas y los importes se recalculan. Construir el payload a
mano significa inventar precios, y un precio inventado en una reserva real es
un cobro real.

Así que aquí no se construye nada: se **lee el form que el portal acaba de
servir**, se le cambia sólo el campo pedido y se devuelve entero. Los precios
del portal viajan tal cual. Si el caller quiere cambiar las fechas y el
portal recalcula al guardar, es el portal quien lo hace.

## Lo que este módulo NO hace

No se ha llamado ni a `set_checkin` ni a `set_checkout` contra el portal. Un
check-in mueve una estancia con huéspedes dentro y un check-out cierra una
factura. Las URLs están leídas del HTML y los tests usan `MockTransport`, pero
"descubierto" no es "verificado": el §5 de `docs/otelms_endpoints.md` lo
deja como pendiente, igual que `save_restrict_close_open`.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from otelms.scraping.auth import get_authenticated_http_session

logger = logging.getLogger(__name__)

BASE = "https://desktop.otelms.com"

CHECKIN_URL = "/reservation_c2/set_checkin/{resid}/status"
CHECKOUT_URL = "/reservation_c2/set_checkout/{resid}/status"

CHECKIN_WIZARD_URL = "/master_c2/step_1/{resid}/?landing_page=folio"
CHECKOUT_WIZARD_URL = "/master_c2/checkout_step_1/{resid}?landing_page=folio"

UPDATE_RESERVATION_URL = "/reservation_c2/update_reservation"

# `landing_page` es lo que el portal usa para saber a qué asistente volver.
# No es decorativo: el mismo form sirve para check-in y para check-out.
LANDING_CHECKIN = "master_checkin"
LANDING_CHECKOUT = "master_checkout"

# Campos que `move_reservation` deja tocar. El resto se copia tal cual.
MOVABLE_FIELDS = ("room_id", "category", "datein", "dateout", "duration")


@asynccontextmanager
async def _client_for(
    hotel_id: str, client: httpx.AsyncClient | None
) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente autenticado, o el que le pase el caller.

    Mismo motivo que en `restrictions._client_for`: `async with` no vale sobre
    un cliente que ya hizo el login, porque httpx sólo admite `__aenter__`
    una vez y sobre un cliente sin abrir.
    """
    if client is not None:
        yield client
        return
    owned = await get_authenticated_http_session(hotel_id)
    try:
        yield owned
    finally:
        await owned.aclose()


def _attr(node: Tag, name: str) -> str | None:
    """Valor de un atributo como `str`.

    BeautifulSoup devuelve `str | list[str]` según el documento, así que sin
    esto mypy se queixa en cada lectura de atributo.
    """
    value = node.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return " ".join(value)


def _form_values(form: Tag) -> dict[str, str]:
    """Todos los campos con nombre del form, tal cual los sirve el portal.

    Los `select` toman la opción marcada; si no hay ninguna, la primera,
    porque es lo que el navegador mandaría. Los checkbox sin marcar se
    omiten, que es también lo que hace el navegador.
    """
    values: dict[str, str] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = _attr(node, "name")
        if not name:
            continue
        if node.name == "select":
            options = node.find_all("option")
            chosen = next((o for o in options if o.has_attr("selected")), None)
            if chosen is None and options:
                chosen = options[0]
            if chosen is None:
                continue
            values[name] = _attr(chosen, "value") or chosen.get_text(strip=True)
        elif node.name == "textarea":
            values[name] = node.get_text()
        else:
            node_type = _attr(node, "type")
            if node_type in ("checkbox", "radio") and not node.has_attr("checked"):
                continue
            values[name] = _attr(node, "value") or ""
    return values


def parse_reservation_form(html: str) -> dict[str, str]:
    """El form `update_reservation` tal cual, como dict plano.

    Los `day_price[day_id]` se conservan con ese nombre, que es como los
    espera el portal.
    """
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"action": UPDATE_RESERVATION_URL})
    if form is None:
        raise ValueError("No se encontró el form update_reservation en la página")
    return _form_values(form)


def parse_reservation_summary(html: str) -> dict[str, str]:
    """Lo mismo, pero sólo los campos que identifican la estancia.

    Sirve para el `GET` de diagnóstico: con esto se puede comprobar qué
    eligió el portal sin construir ningún POST.
    """
    values = parse_reservation_form(html)
    return {
        key: values[key]
        for key in ("reservation_id", "room_id", "category", "datein", "dateout",
                    "duration", "adults", "landing_page")
        if key in values
    }


async def get_reservation_form(
    hotel_id: str,
    reservation_id: str,
    *,
    checkout: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """El form de edición tal como lo sirve el portal, sin tocar nada."""
    template = CHECKOUT_WIZARD_URL if checkout else CHECKIN_WIZARD_URL
    url = f"{BASE}{template.format(resid=reservation_id)}"
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(url)
    values = parse_reservation_form(resp.text)
    logger.info(
        "Reservation form read %s/%s (checkout=%s): %d fields",
        hotel_id, reservation_id, checkout, len(values),
    )
    return values


async def check_in(
    hotel_id: str,
    reservation_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Marca la reserva como check-in.

    NO verificado contra el portal: ver el aviso del módulo.
    """
    url = f"{BASE}{CHECKIN_URL.format(resid=reservation_id)}"
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(url)
    ok = resp.status_code == 200
    if ok:
        logger.info(
            "check_in %s/%s -> HTTP %s (ok=%s)", hotel_id, reservation_id,
            resp.status_code, ok,
        )
    else:
        logger.warning(
            "check_in %s/%s failed -> HTTP %s location=%s body=%r",
            hotel_id, reservation_id, resp.status_code,
            resp.headers.get("location"), resp.text[:300],
        )
    return ok


async def check_out(
    hotel_id: str,
    reservation_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Cierra la estancia y factura.

    NO verificado contra el portal: ver el aviso del módulo.
    """
    url = f"{BASE}{CHECKOUT_URL.format(resid=reservation_id)}"
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(url)
    ok = resp.status_code == 200
    if ok:
        logger.info(
            "check_out %s/%s -> HTTP %s (ok=%s)", hotel_id, reservation_id,
            resp.status_code, ok,
        )
    else:
        logger.warning(
            "check_out %s/%s failed -> HTTP %s location=%s body=%r",
            hotel_id, reservation_id, resp.status_code,
            resp.headers.get("location"), resp.text[:300],
        )
    return ok


async def move_reservation(
    hotel_id: str,
    reservation_id: str,
    *,
    room_id: str | None = None,
    category_id: str | None = None,
    date_in: date | None = None,
    date_out: date | None = None,
    checkout: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """Cambia habitación o fechas reenviando el form del portal entero.

    Sólo se tocan los campos pedidos. Los precios por noche (`day_price`) y
    los importes van tal cual los sirvió el portal, que es la razón de que
    este módulo no construya el payload.

    NO verificado contra el portal: ver el aviso del módulo.
    """
    if all(v is None for v in (room_id, category_id, date_in, date_out)):
        raise ValueError(
            "Hay que cambiar algo: room_id, category_id, date_in o date_out"
        )

    form = await get_reservation_form(
        hotel_id, reservation_id, checkout=checkout, client=client,
    )

    # El paso 1 del check-out pone `dateout` = hoy y deja `duration` en
    # negativo si el huésped todavía no ha llegado (medido: 23565, llegada
    # 2026-10-09, devuelve duration -4). Reenviar ese form tal cual
    # guardaría una estancia de -4 noches, así que si el caller no fija
    # fechas se devuelve el error en vez de mandarlo.
    if date_in is None and date_out is None and form.get("duration", "0").startswith("-"):
        raise ValueError(
            f"La reserva {reservation_id} no ha llegado todavía: el form de "
            "OtelMS trae duration negativo. Pasa date_in/date_out o quita el "
            "check-in antes de moverla."
        )

    if room_id is not None:
        # El form trae `room_id` dos veces (un hidden con la actual y un
        # select). Dict pisa las dos con el mismo valor, que es lo que
        # quiere el portal: los dos campos tienen que coincidir.
        form["room_id"] = room_id
    if category_id is not None:
        form["category"] = category_id
    if date_in is not None:
        form["datein"] = date_in.isoformat()
    if date_out is not None:
        form["dateout"] = date_out.isoformat()
    if date_in is not None or date_out is not None:
        # `duration` es lo que el portal usa para saber cuántas noches son.
        # Recalcularlo aquí evita mandar el viejo y que se guarden fechas
        # incoherentes; los day_price los recalcula el portal.
        inicio = date.fromisoformat(form["datein"])
        fin = date.fromisoformat(form["dateout"])
        form["duration"] = str((fin - inicio).days)

    form.setdefault("landing_page", LANDING_CHECKOUT if checkout else LANDING_CHECKIN)

    async with _client_for(hotel_id, client) as session:
        resp = await session.post(f"{BASE}{UPDATE_RESERVATION_URL}", data=form)
    location = resp.headers.get("location")
    if resp.status_code >= 400 or (location and "login" in location.lower()):
        logger.error(
            "move_reservation %s/%s failed -> HTTP %s location=%s body=%r",
            hotel_id, reservation_id, resp.status_code, location, resp.text[:300],
        )
        raise RuntimeError(
            f"OtelMS move_reservation failed (HTTP {resp.status_code}, location={location})"
        )
    logger.info(
        "move_reservation %s/%s -> HTTP %s (room=%s cat=%s %s..%s location=%s)",
        hotel_id, reservation_id, resp.status_code, room_id, category_id,
        form.get("datein"), form.get("dateout"), location,
    )
    return form


def summarise(form: dict[str, Any]) -> dict[str, Any]:
    """Campos interesantes de un form, para logs y tests."""
    keys = ("reservation_id", "room_id", "category", "datein", "dateout",
            "duration", "adults", "landing_page")
    return {key: form[key] for key in keys if key in form}
