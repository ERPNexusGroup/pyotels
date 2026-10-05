"""Cierre y apertura de fechas (restricciones) contra OtelMS.

Descubierto contra el portal, no deducido. La secuencia real es de tres pasos
y el primero no es opcional:

1. Se **selecciona** arrastrando sobre la rejilla. Al soltar, el navegador
   manda cada celda a `/reservation_c2/ajax_calendar_restricts` con el nombre
   `resstrict_data` (con tres "s", es del portal) indexado:
   `resstrict_data[0][rate_id]`, `[date]` (el day_id), `[fulldate]` (ISO) y
   `[category_id]`. El servidor guarda la selección en sesión y devuelve el
   modal de edición.

2. El modal (`#dialogForm`) lleva las fechas (`datein`, `dateout`), el estado
   (`closed`) y los mínimos de estancia.

3. "Guardar" serializa ese form y lo manda a `/reservation_c2/save_restricts`.

**El paso 1 no se puede saltar.** Un POST directo a `save_restricts` responde
`{"ok":1, "count_restricts_data":0}` y no aplica nada: el portal acepta la
llamada, dice que fue bien y no cambia una sola celda. Sin selección no hay
qué Guardar. Está reproducido en `tests/manual/test_restrict_save_roundtrip.py`
(fallo) y `tests/manual/test_restrict_full_flow.py` (funciona).

Los valores de `closed` son 1 = Cerrado, 0 = Abierto, 2 = No cambiar.

OJO con el otro endpoint de la misma página, `save_restrict_close_open`, cuyos
botones `close_save()` / `open_save()` ponen `restrict_type` 1 y 2. No se usa
aquí: su form no lleva categorías y no se ha ejercido contra el portal, así que
qué celdas tocarías no está verificado.

OtelMS cierra por CATEGORÍA, no por número de habitación: la 305 pertenece a
la categoría "Matrimonial". Por eso todo aquí va por category_id + rate_id.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from otelms.scraping.auth import get_authenticated_http_session

logger = logging.getLogger(__name__)

# Category name → ID mapping (from /reservation_c2/restrict_calendar)
CATEGORY_IDS: dict[str, str] = {
    "Matrimonial": "13",
    "Doble Individual": "14",
    "Triple": "15",
    "Quadruple": "16",
    "Quintuple": "17",
    "Sextuple": "18",
    "Suite Matrimonial": "19",
    "Suite Familiar": "20",
    "Overbooking": "21",
}

# Valores de la tarifa (select `restrict_rates[]` de la página)
RATE_STANDARD = "1"
RATE_HOLIDAYS = "2"

# Valores del select `closed` del modal
CLOSED = "1"
OPEN = "0"
KEEP = "2"

CALENDAR_URL = "/reservation_c2/restrict_calendar"
SELECT_URL = "/reservation_c2/ajax_calendar_restricts"
SAVE_URL = "/reservation_c2/save_restricts"
DELETE_URL = "/reservation_c2/delete_restricts"

# Clase que el servidor pone en una celda cerrada. Una celda abierta trae
# `calendar_td ui-selectee` y su `<div class="current_data3">` con el día; una
# cerrada pierde ese div y gana `bg_padlock` + `calendar_price_change`.
CLOSED_CELL_CLASS = "bg_padlock"

AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": CALENDAR_URL,
}

WEEKDAYS = ("week[0]", "week[1]", "week[2]", "week[3]", "week[4]", "week[5]", "week[6]")


@asynccontextmanager
async def _client_for(
    hotel_id: str, client: httpx.AsyncClient | None
) -> AsyncIterator[httpx.AsyncClient]:
    """Usa el cliente inyectado o abre una sesión autenticada nueva."""
    if client is not None:
        yield client
        return
    owned = await get_authenticated_http_session(hotel_id)
    try:
        yield owned
    finally:
        # `async with` sobre el cliente no vale aquí: get_authenticated_http_
        # session ya lo usó para el login, y httpx sólo admite __aenter__ una
        # vez, sobre un cliente sin abrir.
        await owned.aclose()


# ============================================================
# Parsing
# ============================================================
def _attr(node: Any, name: str) -> str | None:
    """Atributo de un nodo como texto plano.

    BeautifulSoup tipa `get()` como `str | AttributeValueList | None`; en esta
    rejilla siempre es `str`, pero el tipo obliga a Narrowing en cada uso.
    """
    value = node.get(name)
    if value is None:
        return None
    return value if isinstance(value, str) else " ".join(value)


def _as_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_restriction_cells(
    html: str,
    *,
    category_ids: Sequence[str] | None = None,
    rate_id: str | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
) -> list[dict[str, Any]]:
    """Celdas de la rejilla de restricciones, con su estado.

    Cada celda sale con `category_id`, `rate_id`, `day_id`, `date` (ISO) y
    `closed`. El estado se lee de las clases del `<td>`, no de un atributo: el
    portal no serializa el estado en la celda, sólo lo pone en el `<div>` que
    la propia JS elimina al cerrar.
    """
    soup = BeautifulSoup(html, "html.parser")
    wanted_categories = {str(c) for c in category_ids} if category_ids else None
    start, end = _as_date(date_from), _as_date(date_to)

    cells: list[dict[str, Any]] = []
    for td in soup.select("td.calendar_td"):
        cell_category = _attr(td, "category_id")
        cell_rate = _attr(td, "rate_id")
        cell_date = _as_date(_attr(td, "fulldate"))
        day_id = _attr(td, "date")
        if not (cell_category and cell_rate and cell_date and day_id):
            continue
        if wanted_categories is not None and cell_category not in wanted_categories:
            continue
        if rate_id is not None and cell_rate != str(rate_id):
            continue
        if start is not None and cell_date < start:
            continue
        if end is not None and cell_date > end:
            continue
        cells.append({
            "category_id": cell_category,
            "rate_id": cell_rate,
            "day_id": day_id,
            "date": cell_date.isoformat(),
            "closed": CLOSED_CELL_CLASS in (_attr(td, "class") or "").split(),
        })
    logger.info("Restriction cells parsed: %d", len(cells))
    return cells


def parse_closed_cells(html: str, **filters: Any) -> list[dict[str, Any]]:
    """Sólo las celdas cerradas."""
    return [cell for cell in parse_restriction_cells(html, **filters) if cell["closed"]]


def parse_modal_state(modal_html: str) -> dict[str, Any]:
    """Estado que el servidor refleja en el modal de una selección.

    El `<select name="closed">` llega con la opción vigente marcada. Es la
    forma de leer si un día ya estaba cerrado sin cerrar nada.
    """
    soup = BeautifulSoup(modal_html, "html.parser")
    state: dict[str, Any] = {}
    for name in ("category_id", "rate_id", "datein", "dateout"):
        node = soup.find(attrs={"name": name})
        if node is not None:
            state[name] = node.get("value")
    closed_select = soup.find("select", attrs={"name": "closed"})
    if closed_select is not None:
        chosen = closed_select.find("option", selected=True)
        state["closed"] = chosen.get("value") if chosen else None
    return state


# ============================================================
# Lectura
# ============================================================
async def get_restrictions(
    hotel_id: str,
    *,
    category_ids: Sequence[str] | None = None,
    rate_id: str | None = RATE_STANDARD,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Celdas cerradas ahora mismo en la rejilla de restricciones."""
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(CALENDAR_URL)
    closed = parse_closed_cells(
        resp.text,
        category_ids=category_ids,
        rate_id=rate_id,
        date_from=date_from,
        date_to=date_to,
    )
    logger.info("Closed dates fetched: %d", len(closed))
    return closed


async def get_categories(
    hotel_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Categorías de habitación de la rejilla de restricciones."""
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(CALENDAR_URL)
    soup = BeautifulSoup(resp.content, "html.parser")
    cat_select = soup.find("select", {"name": "categories[]"})
    if not cat_select:
        return []
    return [opt.get_text(strip=True) for opt in cat_select.find_all("option")]


# ============================================================
# Escritura
# ============================================================
def _select_payload(cells: Sequence[dict[str, Any]]) -> dict[str, str]:
    """El `resstrict_data` indexado que espera ajax_calendar_restricts.

    Ojo al nombre de los campos: `date` es el day_id numérico de la celda y
    `fulldate` es la fecha ISO. Mandarlos cambiados no da error, pero el
    portal no reconoce la selección.
    """
    payload: dict[str, str] = {}
    for idx, cell in enumerate(cells):
        values = {
            "rate_id": cell.get("rate_id"),
            "date": cell.get("day_id"),
            "fulldate": cell.get("date"),
            "category_id": cell.get("category_id"),
        }
        for key, value in values.items():
            payload[f"resstrict_data[{idx}][{key}]"] = str(value)
    return payload


def _save_payload(
    cells: Sequence[dict[str, Any]],
    closed: str,
    *,
    delete: bool = False,
) -> dict[str, str]:
    """El form del modal serializado, tal como lo manda save_restricts().

    Todos los días de la semana van marcados: el modal los traechecked de
    fábrica y así se comportó en el round-trip real.
    """
    first = cells[0]
    date_from = first.get("fulldate") or first.get("date")
    date_to = cells[-1].get("fulldate") or cells[-1].get("date")
    payload = {
        "delete_action": "1" if delete else "0",
        "category_id": str(first.get("category_id")),
        "rate_id": str(first.get("rate_id")),
        "datein": str(date_from),
        "dateout": str(date_to),
        "closed": closed,
        "closedonarrival": KEEP,
        "closedondeparture": KEEP,
        "minstaythrought": "0",
        "minstayarrival": "0",
        "maxstay": "0",
    }
    for day in WEEKDAYS:
        payload[day] = "1"
    return payload


async def _select(session: httpx.AsyncClient, cells: Sequence[dict[str, Any]]) -> str:
    """Paso 1: registrar la selección. Devuelve el modal."""
    resp = await session.post(
        SELECT_URL,
        data=_select_payload(cells),
        headers=AJAX_HEADERS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Select failed: {resp.status_code} {resp.text[:200]}")
    return resp.text


async def set_dates_state(
    hotel_id: str,
    cells: Sequence[dict[str, Any]],
    closed: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Cierra (`closed=CLOSED`) o abre (`closed=OPEN`) un conjunto de celdas.

    Todas las celdas deben ser de la misma categoría y tarifa: así funciona el
    portal, donde el modal edita una fila (category_id + rate_id) y un rango de
    fechas.

    Devuelve el JSON del portal, que incluye `count_restricts_data`: el número
    de días realmente afectados. Si vale 0, no se cerró nada aunque `ok` sea 1,
    y eso casi siempre significa que faltó el paso de selección.
    """
    if not cells:
        raise ValueError("No hay celdas que modificar")
    categories = {str(c.get("category_id")) for c in cells}
    rates = {str(c.get("rate_id")) for c in cells}
    if len(categories) > 1 or len(rates) > 1:
        raise ValueError(
            f"Todas las celdas deben ser de la misma categoría y tarifa; "
            f"ven {len(categories)} categorías y {len(rates)} tarifas"
        )

    async with _client_for(hotel_id, client) as session:
        await _select(session, cells)
        resp = await session.post(
            SAVE_URL, data=_save_payload(cells, closed), headers=AJAX_HEADERS
        )

    try:
        result: dict[str, Any] = resp.json()
    except ValueError:
        result = {"_raw": resp.text[:200]}

    applied = result.get("count_restricts_data", 0)
    logger.info(
        "Dates %s: %d cells, %d days applied",
        "closed" if closed == CLOSED else "opened", len(cells), applied,
    )
    if resp.status_code != 200 or result.get("ok") != 1:
        raise RuntimeError(f"Save failed: {resp.status_code} {resp.text[:200]}")
    if not applied:
        logger.warning("Portal confirmed ok=1 but applied 0 days: nothing was changed")
    result["requested_cells"] = len(cells)
    return result


async def close_dates(
    hotel_id: str,
    start_date: str | date,
    end_date: str | date,
    categories: Sequence[str] | None = None,
    *,
    rate_id: str = RATE_STANDARD,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Cierra un rango de fechas para una o más categorías.

    Args:
        hotel_id: Hotel ID (18330).
        start_date: Fecha inicio (YYYY-MM-DD).
        end_date: Fecha fin (YYYY-MM-DD).
        categories: Nombres de categoría. Si None, todas.
        rate_id: Tarifa; 1 = Standard, 2 = Feriados.
        client: Sesión HTTP ya autenticada. Si no se pasa, se abre una.
    """
    return await _apply_range(
        hotel_id, start_date, end_date, categories, rate_id, CLOSED, client=client
    )


async def open_dates(
    hotel_id: str,
    start_date: str | date,
    end_date: str | date,
    categories: Sequence[str] | None = None,
    *,
    rate_id: str = RATE_STANDARD,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Abre (desbloquea) un rango de fechas para una o más categorías."""
    return await _apply_range(
        hotel_id, start_date, end_date, categories, rate_id, OPEN, client=client
    )


async def _apply_range(
    hotel_id: str,
    start_date: str | date,
    end_date: str | date,
    categories: Sequence[str] | None,
    rate_id: str,
    closed: str,
    *,
    client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """Traduce un rango de fechas a celdas y las cierra/abre una a una.

    El portal sólo edita una fila (categoría + tarifa) por llamada, así que un
    rango que abarque varias categorías son varias llamadas.
    """
    names = list(categories) if categories else list(CATEGORY_IDS)
    if categories:
        wanted = [CATEGORY_IDS[c] for c in categories]
    else:
        wanted = list(CATEGORY_IDS.values())

    async with _client_for(hotel_id, client) as session:
        resp = await session.get(CALENDAR_URL)
        cells = parse_restriction_cells(
            resp.text,
            category_ids=wanted,
            rate_id=rate_id,
            date_from=start_date,
            date_to=end_date,
        )

        results: dict[str, Any] = {}
        for category_id in wanted:
            block = [c for c in cells if c["category_id"] == category_id]
            if not block:
                logger.warning(
                    "No cells in range for category %s (%s - %s)",
                    category_id, start_date, end_date,
                )
                continue
            await _select(session, block)
            saved = await session.post(
                SAVE_URL,
                data=_save_payload(block, closed),
                headers=AJAX_HEADERS,
            )
            try:
                results[names[wanted.index(category_id)]] = saved.json()
            except ValueError:
                results[names[wanted.index(category_id)]] = {"_raw": saved.text[:200]}

    total = sum(r.get("count_restricts_data", 0) for r in results.values() if isinstance(r, dict))
    logger.info(
        "Range %s %s - %s: %d days applied",
        "closed" if closed == CLOSED else "opened", start_date, end_date, total,
    )
    return {"count_restricts_data": total, "by_category": results}
