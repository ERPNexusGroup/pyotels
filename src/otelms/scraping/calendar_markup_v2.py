"""
Parser del markup ACTUAL del calendario OtelMS (migración 2026, verificado
contra HTML real del 2026-09-10, hotel 18330).

Diferencias vs las constantes legacy (OtelMSSelectors):
  - Filas:        tr.calendar_tr (+ btn_close_box{cat_id} en filas de habitación)
  - Celdas:       td.calendar_td con atributos room_id / day_id (/ category_id)
                  (antes: td.calendar_cell; NO existen th.calendar_date)
  - Fila resumen por categoría: celdas con room_id="0" + category_id + div.calendar_sum
  - Reservas:     div.calendar_item[resid][status] + tooltip en data-title
                  (formato "Reserva №ID (Tipo), Canal" + divs "Clave: valor")
  - day_id:       serial de fecha = días desde 1970-01-01  (20706 = 2026-09-10)
  - Nombres de categoría: sidebar div.calendar_rooms_dott, en orden de bloques
  - Días bloqueados: td.calendar_td.bg_padlock

NOTA DE ALCANCE: la vista calendario NO distingue check-in (todo llega con
status '1' / tipo Reservación). La ocupación se deriva por noches vendidas
(check_in <= fecha < check_out); ver RoomRepository.get_occupied_for_date.

Todo puro (sin browser): entrada HTML, salida dicts compatibles con
SyncService._persist_calendar / _persist_categories.
"""
import html as _ihtml
import re
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup

from otelms.utils.logging import get_logger

logger = get_logger(__name__)

EPOCH = date(1970, 1, 1)

TABLE_CLASS = "calendar_table"
ROW_CLASS = "calendar_tr"
CELL_CLASS = "calendar_td"
ITEM_CLASS = "calendar_item"
SUMMARY_CLASS = "calendar_sum"
SIDEBAR_CLASS = "calendar_rooms_dott"
LOCKED_CLASS = "bg_padlock"
ROW_BOX_PREFIX = "btn_close_box"


def day_id_to_date(day_id: str | int) -> str:
    """Convierte day_id (días desde epoch) a 'YYYY-MM-DD'."""
    return (EPOCH + timedelta(days=int(day_id))).isoformat()


def parse_tooltip_v2(data_title: str) -> dict[str, str]:
    """Parsea el tooltip data-title (HTML escapado) a dict plano.

    Formato: <p class='tooltip_inside'> + divs; primero
    'Reserva №ID (Tipo), Canal', resto 'Clave: valor'.
    """
    fields: dict[str, str] = {}
    if not data_title:
        return fields
    soup = BeautifulSoup(_ihtml.unescape(data_title), "lxml")
    divs = soup.find_all("div")
    if not divs:
        return fields
    first = divs[0].get_text(strip=True)
    match = re.match(r"Reserva\s*№(\d+)\s*\(([^)]+)\)(?:,\s*(.+))?", first)
    if match:
        fields["reservation_id"] = match.group(1)
        fields["reservation_type"] = match.group(2)
        if match.group(3):
            fields["channel"] = match.group(3).strip()
    for div in divs[1:]:
        text = div.get_text(strip=True)
        if ":" in text:
            key, _, value = text.partition(":")
            # Claves normalizadas a minúsculas ("Llegada" -> "llegada")
            # porque el markup mezcla capitalización.
            fields[key.strip().lower()] = value.strip()
    return fields


def _category_name_map(soup: BeautifulSoup) -> dict[str, str]:
    """Mapea category_id -> nombre usando bloques (orden) + sidebar (orden).

    Si los conteos no coinciden, fallback a 'Categoría {id}'.
    """
    table = soup.find("table", class_=TABLE_CLASS)
    block_ids: list[str] = []
    if table:
        for tb in table.find_all("tbody", recursive=False):
            first_td = tb.find("td", recursive=False) or tb.find("td")
            cid = first_td.get("category_id") if first_td else None
            if not cid:
                for tr in tb.find_all("tr", recursive=False):
                    for c in tr.get("class", []):
                        if c.startswith(ROW_BOX_PREFIX):
                            cid = c[len(ROW_BOX_PREFIX):]
                            break
                    if cid:
                        break
            if cid and cid not in block_ids:
                block_ids.append(str(cid))

    names = [
        d.get_text(strip=True)
        for d in soup.find_all("div", class_=SIDEBAR_CLASS)
        if d.get_text(strip=True)
    ]
    mapping = {}
    if len(names) == len(block_ids):
        mapping = dict(zip(block_ids, names, strict=True))
    else:
        logger.warning(
            "Sidebar/block count mismatch",
            sidebar=len(names),
            blocks=len(block_ids),
        )
    return mapping


def parse_categories_v2(html: str) -> list[dict[str, Any]]:
    """Categorías + habitaciones del markup actual.

    Retorna [{id, name, rooms: [{id, name, category_id}]}] compatible con
    CategoryRepository.upsert_with_rooms / RoomRepository.upsert.
    Room id/name = número de habitación (room_id del markup).
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_=TABLE_CLASS)
    if not table:
        return []
    names = _category_name_map(soup)

    categories: list[dict[str, Any]] = []
    by_cat: dict[str, dict[str, Any]] = {}
    for tb in table.find_all("tbody", recursive=False):
        # El markup real trae UN tbody por fila (resumen o habitación),
        # así que se agrupa por categoría a lo largo de todos los tbodies.
        for tr in tb.find_all("tr", recursive=False):
            cat_id: str | None = None
            for c in tr.get("class", []):
                if c.startswith(ROW_BOX_PREFIX):
                    cat_id = str(c[len(ROW_BOX_PREFIX):])
            cells = tr.find_all("td", recursive=False)
            if not cells:
                continue
            first = cells[0]
            if first.get("room_id") == "0" and first.get("category_id"):
                cat_id = str(first.get("category_id"))
                by_cat.setdefault(cat_id, {"id": cat_id, "name": "", "rooms": []})
                continue  # fila resumen, no es habitación
            room_id = first.get("room_id")
            if not room_id or room_id == "0" or not cat_id:
                continue
            entry = by_cat.setdefault(cat_id, {"id": cat_id, "name": "", "rooms": []})
            if str(room_id) not in {r["id"] for r in entry["rooms"]}:
                entry["rooms"].append({
                    "id": str(room_id),
                    "name": str(room_id),
                    "category_id": cat_id,
                })
    for cat_id, entry in by_cat.items():
        if entry["rooms"]:
            entry["name"] = names.get(cat_id, f"Categoría {cat_id}")
            categories.append(entry)
    return categories


def parse_grid_v2(html: str) -> dict[str, Any]:
    """Reservas + categorías + locks del markup actual.

    Retorna {"cells", "categories", "day_id_to_date", "locks"} donde cells
    son dicts compatibles con SyncService._persist_calendar y locks es
    [(room_id, date)] de celdas bg_padlock FUTURAS (informativo; el sync
    aún no persiste bloqueos — ver RoomAvailability / close-open).
    """
    soup = BeautifulSoup(html, "lxml")
    categories = parse_categories_v2(html)
    room_to_category = {
        room["id"]: {"id": cat["id"], "name": cat["name"]}
        for cat in categories
        for room in cat["rooms"]
    }

    table = soup.find("table", class_=TABLE_CLASS)
    cells: list[dict[str, Any]] = []
    locks: list[dict[str, str]] = []
    day_id_to_date: dict[str, str] = {}
    today = date.today().isoformat()
    if table:
        for td in table.find_all("td", class_=CELL_CLASS):
            raw_day = td.get("day_id")
            if not raw_day:
                continue
            raw_day = str(raw_day)
            iso_date = day_id_to_date.get(raw_day)
            if iso_date is None:
                try:
                    iso_date = day_id_to_date_table(raw_day)
                except (TypeError, ValueError):
                    continue
                day_id_to_date[raw_day] = iso_date

            raw_room = td.get("room_id")
            if raw_room and raw_room != "0" and LOCKED_CLASS in (td.get("class") or []):
                if iso_date >= today:
                    locks.append({"room_id": str(raw_room), "date": iso_date})

            item = td.find("div", class_=ITEM_CLASS)
            if item is None:
                continue
            resid = item.get("resid")
            if not resid:
                continue
            fields = parse_tooltip_v2(item.get("data-title", ""))
            # Alias con mayúscula para compatibilidad con _persist_calendar.
            fields.setdefault("Fuente", fields.get("fuente", ""))
            cat_info = room_to_category.get(str(raw_room), {"id": "", "name": ""})
            try:
                status = int(item.get("status") or 1)
            except (TypeError, ValueError):
                status = 1
            check_in = fields.get("llegada", iso_date)
            check_out = fields.get("salida", iso_date)
            cells.append({
                "room_id": str(raw_room),
                "room_name": str(raw_room),
                "category_id": cat_info["id"],
                "category_name": cat_info["name"],
                "date": check_in,
                "day_id": str(raw_day),
                "cell_status": "occupied",
                "reservation_id": str(resid),
                "guest_name": fields.get("huésped", "").strip(),
                "check_in": check_in,
                "check_out": check_out,
                "reservation_status": status,
                "guest_count": int(fields["cantidad de huéspedes"])
                if fields.get("cantidad de huéspedes", "").isdigit() else 1,
                "balance": fields.get("balance") or None,
                "fields": fields,
                "comments": fields.get("comentarios", ""),
            })

    logger.info(
        "Calendar v2 parsed",
        categories=len(categories),
        reservations=len(cells),
        locks=len(locks),
    )
    return {
        "cells": cells,
        "categories": categories,
        "day_id_to_date": day_id_to_date,
        "locks": locks,
    }


def day_id_to_date_table(day_id: str) -> str:
    """Helper nombrado para el mapeo day_id -> fecha (testeable)."""
    return day_id_to_date(day_id)
