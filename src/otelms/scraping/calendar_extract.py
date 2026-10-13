"""Extractores de datos de calendar y folios desde HTML de OtelMS."""
import html
import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag


def _attr(node: Tag, name: str) -> str:
    """Lee un atributo como str, aplastando listas de valores si el HTML las trae.

    bs4 tipa `Tag.get()` como `str | AttributeValueList`; sin esta
    helper cada `item.get("resid")` obliga a un cast a mano en cada uso.
    """
    value = node.get(name)
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


def parse_tooltip(data_title: str) -> dict[str, str]:
    """Parsea el HTML dentro de data-title (con entidades escapadas).

    El primer div es especial:
      "Reserva №23229 (Reservación), Venta directa"
    Los demás usan "key: value".
    """
    decoded = html.unescape(data_title)
    soup = BeautifulSoup(decoded, "html.parser")
    divs = soup.find_all("div")

    fields: dict[str, str] = {}
    if divs:
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
                fields[key.strip().lower()] = value.strip()

    return fields


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    date_str = date_str.strip()
    if date_str in ("0000-00-00", "0000-00-00 00:00:00"):
        return None
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def extract_reservations_from_calendar(html_content: str) -> list[dict]:
    """Extrae todos los elementos con atributo `resid` (calendar_item)
    y parsea el `data-title` (tooltip con detalles de la reserva).

    Incluye room_id del td calendario contenedor para asignar la reserva
    a la habitación correcta (el folio a veces da un número distinto).
    """
    soup = BeautifulSoup(html_content, "html.parser")
    res_items = soup.find_all(attrs={"resid": True})

    reservations = []
    for item in res_items:
        resid = _attr(item, "resid")
        status = _attr(item, "status") or "0"
        data_title = _attr(item, "data-title")
        fields = parse_tooltip(data_title) if data_title else {}

        # Buscar room_id en el td calendario contenedor (ancestros)
        room_id = ""
        parent_td = item.find_parent("td", class_="calendar_td")
        if parent_td:
            room_id = _attr(parent_td, "room_id")

        reservations.append({
            "resid": int(resid) if resid else 0,
            "reservation_id": int(fields.get("reservation_id", "0") or "0"),
            "status": int(status) if status else 0,
            "reservation_type": fields.get("reservation_type", ""),
            "channel": fields.get("channel", ""),
            "guest_name": fields.get("huésped", "").strip(),
            "check_in": _parse_date(fields.get("llegada", "")),
            "check_out": _parse_date(fields.get("salida", "")),
            "created_at": _parse_date(fields.get("fecha de creación", "")),
            "modified_at": _parse_date(fields.get("fecha de modificación", "")),
            "guest_count": int(fields.get("cantidad de huéspedes", "0"))
                if fields.get("cantidad de huéspedes", "").isdigit() else None,
            "balance": fields.get("balance", ""),
            "phone": fields.get("teléfono", ""),
            "email": fields.get("email", ""),
            "user": fields.get("usuario", ""),
            "comments": fields.get("comentarios", ""),
            "room_id": room_id,
        })

    return reservations
