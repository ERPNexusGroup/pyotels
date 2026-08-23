"""
Extractores de datos de folio/reservas desde HTML de OtelMS.

URLs conocidas:
- /reservation_c2/folio/{reserv_id} — "Prevista de la reserva" (invoice)
- /reservation_c2/guestfolio/{reserv_id} — perfil de huésped (limitado)
- /reservation_c2/calendar — lista de todas las reservas
"""
import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from bs4 import BeautifulSoup


def parse_folio(html_content: str, reservation_id: str | int) -> dict:
    """Parsea el HTML del folio y extrae servicios, pagos y charges.

    Tablas en /reservation_c2/folio/{id}:
      T2: Charges (ID, Nombre, Entidad, Cantidad, Precio, Importe)
      T3: Payments (Fecha, Fecha creación, #, Entidad, Descripción, Tipo, Cantidad, Método, Card, Estado)
      T8: Room charges (Fecha, Descripción, Importe)
      T11: Services (Nombre, Сумма)
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
    result = {
        "reservation_id": str(reservation_id),
        "services": [],
        "payments": [],
        "room_charges": [],
    }

    # Tabla 2: Charges/Servicios
    if len(tables) >= 3:
        rows = tables[1].find_all("tr")[1:]
        for row in rows:
            cells = row.find_all(["td", "th"])
            values = [c.get_text(strip=True) for c in cells]
            non_empty = [v for v in values if v.strip()]
            if "Total:" in values:
                continue
            if len(non_empty) >= 3:
                result["services"].append({
                    "id": non_empty[0],
                    "name": non_empty[1],
                    "legal_entity": non_empty[2],
                    "quantity": _parse_decimal(non_empty[3]) if len(non_empty) > 3 else None,
                    "price": _parse_decimal(non_empty[4]) if len(non_empty) > 4 else None,
                    "amount": _parse_decimal(non_empty[5]) if len(non_empty) > 5 else None,
                })

    # Tabla 3: Pagos
    if len(tables) >= 4:
        rows = tables[2].find_all("tr")[1:]
        for row in rows:
            cells = row.find_all(["td", "th"])
            values = [c.get_text(strip=True) for c in cells]
            non_empty = [v for v in values if v.strip()]
            if "Total:" in values:
                continue
            if len(non_empty) >= 6:
                result["payments"].append({
                    "date": non_empty[0],
                    "invoice_num": non_empty[2],
                    "legal_entity": non_empty[3],
                    "description": non_empty[4],
                    "amount": _parse_decimal(non_empty[6]) if len(non_empty) > 6 else None,
                    "payment_type": non_empty[7] if len(non_empty) > 7 else "",
                    "card_number": non_empty[8] if len(non_empty) > 8 else "",
                    "card_status": non_empty[9] if len(non_empty) > 9 else "",
                })

    # Tabla 8: Room charges
    if len(tables) >= 9:
        rows = tables[7].find_all("tr")[1:]
        for row in rows:
            cells = row.find_all(["td", "th"])
            values = [c.get_text(strip=True) for c in cells]
            non_empty = [v for v in values if v.strip()]
            if len(non_empty) >= 2:
                result["room_charges"].append({
                    "date": non_empty[0],
                    "description": non_empty[1],
                    "amount": _parse_decimal(non_empty[2]) if len(non_empty) > 2 else None,
                })

    return result


def _parse_decimal(val: str) -> Optional[Decimal]:
    if not val:
        return None
    try:
        return Decimal(val.replace(",", ".").replace("$", "").replace("€", "").strip())
    except (InvalidOperation, TypeError):
        return None


def extract_reservations_from_calendar(html_content: str) -> list[dict]:
    """Extrae lista de reservas del HTML del calendar.

    Busca todos los elementos con atributo `resid` (calendar_item) y parsea
    su `data-title` (tooltip con detalles de la reserva).
    """
    soup = BeautifulSoup(html_content, "html.parser")
    res_items = soup.find_all(attrs={"resid": True})

    reservations = []
    for item in res_items:
        resid = item.get("resid")
        status = item.get("status", "0")
        data_title = item.get("data-title", "")

        fields = {}
        if data_title:
            decoded = html.unescape(data_title)
            tooltip_soup = BeautifulSoup(decoded, "html.parser")
            divs = tooltip_soup.find_all("div")
            if divs:
                # Primer div: "Reserva №23229 (Reservación), Venta directa"
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
            "guest_count": int(fields.get("cantidad de huéspedes", "0")) if fields.get("cantidad de huéspedes", "").isdigit() else None,
            "balance": fields.get("balance", ""),
            "phone": fields.get("teléfono", ""),
            "email": fields.get("email", ""),
            "comments": fields.get("comentarios", ""),
        })

    return reservations


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.strip())
    except (ValueError, TypeError):
        return None
