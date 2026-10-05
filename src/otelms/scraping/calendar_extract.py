"""Extractores de datos de calendar y folios desde HTML de OtelMS."""
import html
import re
from datetime import datetime

from bs4 import BeautifulSoup


def parse_tooltip(data_title: str) -> dict:
    """Parsea el HTML dentro de data-title (con entidades escapadas).

    El primer div es especial:
      "Reserva №23229 (Reservación), Venta directa"
    Los demás usan "key: value".
    """
    decoded = html.unescape(data_title)
    soup = BeautifulSoup(decoded, "html.parser")
    divs = soup.find_all("div")

    fields = {}
    if divs:
        first = divs[0].get_text(strip=True)
        match = re.match(r"Reserva\s*№(\d+)\s*\(([^)]+)\)(?:,\s*(.+))?", first)
        if match:
            fields["reservation_id"] = int(match.group(1))
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
    """
    soup = BeautifulSoup(html_content, "html.parser")
    res_items = soup.find_all(attrs={"resid": True})

    reservations = []
    for item in res_items:
        resid = item.get("resid")
        status = item.get("status", "0")
        data_title = item.get("data-title", "")
        fields = parse_tooltip(data_title) if data_title else {}

        reservations.append({
            "resid": int(resid) if resid else 0,
            "reservation_id": fields.get("reservation_id", 0),
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
        })

    return reservations
