"""Extraer todos los datos de reservas del calendar usando data-title."""
import re
import html
import json
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
        # Primer div: "Reserva №ID (Tipo), Canal"
        first = divs[0].get_text(strip=True)
        match = re.match(r"Reserva\s*№(\d+)\s*\(([^)]+)\)(?:,\s*(.+))?", first)
        if match:
            fields["reservation_id"] = int(match.group(1))
            fields["reservation_type"] = match.group(2)
            if match.group(3):
                fields["channel"] = match.group(3).strip()

        # Resto: "key: value"
        for div in divs[1:]:
            text = div.get_text(strip=True)
            if ":" in text:
                key, _, value = text.partition(":")
                fields[key.strip().lower()] = value.strip()

    return fields


def extract_all_reservations(html_content: str) -> list[dict]:
    """Extrae todas las reservas del HTML del calendar."""
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
            "check_in": fields.get("llegada", ""),
            "check_out": fields.get("salida", ""),
            "created_at": fields.get("fecha de creación", ""),
            "modified_at": fields.get("fecha de modificación", ""),
            "guest_count": int(fields.get("cantidad de huéspedes", "0"))
                if fields.get("cantidad de huéspedes", "").isdigit() else None,
            "balance": fields.get("balance", ""),
            "phone": fields.get("teléfono", ""),
            "email": fields.get("email", ""),
            "user": fields.get("usuario", ""),
            "comments": fields.get("comentarios", ""),
        })

    return reservations


if __name__ == "__main__":
    with open("calendario_debug.html", "r", encoding="utf-8") as f:
        content = f.read()

    reservations = extract_all_reservations(content)
    print(f"Total: {len(reservations)}")
    print(json.dumps(reservations[:3], indent=2, ensure_ascii=False))