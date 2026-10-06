"""
Extractores de datos de folio/reservas desde HTML de OtelMS.

URLs conocidas:
- /reservation_c2/folio/{reserv_id} — "Prevista de la reserva" (invoice)
- /reservation_c2/guestfolio/{reserv_id} — perfil de huésped (limitado)
- /reservation_c2/calendar — lista de todas las reservas

Las columnas del folio se localizan por el texto de su cabecera, nunca por
posición: las tablas traen celdas vacías y el HTML es server-side, así que
filtrar las vacías y leer por índice desplaza todos los campos en cuanto
una celda se rellena. Ver docs/otelms_endpoints.md §3.
"""
import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Tag

# Índices de tabla dentro del folio. Confirmados contra el portal: el folio
# trae 11 tablas y los cargos van en la 1, los pagos en la 2 y el precio por
# noche en la 7. Ver docs/otelms_endpoints.md §3.1.
_CHARGES_TABLE = 1
_PAYMENTS_TABLE = 2
_ROOM_CHARGES_TABLE = 7


def _column_indexes(table: Tag) -> dict[str, int]:
    """Mapea el texto de cada cabecera de columna a su índice de celda.

    Se resuelve una sola vez por tabla y luego cada campo se lee por su
    columna, de modo que una celda vacía en medio no arrastra al resto.
    """
    head_row = table.find("tr")
    if head_row is None:
        return {}
    indexes: dict[str, int] = {}
    for idx, th in enumerate(head_row.find_all(["th", "td"])):
        label = th.get_text(strip=True)
        if label and label not in indexes:
            indexes[label] = idx
    return indexes


def _attr(node: Tag, name: str) -> str:
    """Lee un atributo como str, aplastando listas de valores si el HTML las trae.

    bs4 tipa `Tag.get()` como `str | AttributeValueList`; sin esta
    helper cada `item.get("resid")` obliga a un cast a mano en cada uso.
    """
    value = node.get(name)
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


def _cell(cells: list[str], indexes: dict[str, int], *labels: str) -> str:
    """Primer valor no vacío entre varias etiquetas posibles de cabecera."""
    for label in labels:
        idx = indexes.get(label)
        if idx is not None and idx < len(cells):
            value = cells[idx].strip()
            if value:
                return value
    return ""


def parse_folio(html_content: str, reservation_id: str | int) -> dict:
    """Parsea el HTML del folio y extrae servicios, pagos y charges.

    Tablas en /reservation_c2/folio/{id} (índices confirmados en
    docs/otelms_endpoints.md §3.1):
      T1: Charges  — Fecha y hora | № | Título | Entidad legal |
                     Descripción | Número | Precio | Cantidad
      T2: Payments — Fecha de pago | Fecha de creación | № | Entidad legal |
                     Descripción | Tipo | Cantidad | Método de pago |
                     vPOS Número | vPOS Estado | Сheque fiscal
      T7: Room charges — Fecha | Precio por una noche | Precio

    En T1 la columna "Cantidad" **no** es el número de unidades sino el
    importe de la línea; las unidades están en "Número". En T2 "Cantidad" sí
    es el importe del pago.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
    result: dict[str, Any] = {
        "reservation_id": str(reservation_id),
        "services": [],
        "payments": [],
        "room_charges": [],
    }

    # Tabla 1: cargos. La fila de total del pie no es un cargo.
    if len(tables) > _CHARGES_TABLE:
        table = tables[_CHARGES_TABLE]
        indexes = _column_indexes(table)
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells or any(c.rstrip(":") == "Total" for c in cells):
                continue
            line_no = _cell(cells, indexes, "№", "N°")
            title = _cell(cells, indexes, "Título", "Titulo")
            if not line_no or not title:
                continue
            result["services"].append({
                "id": line_no,
                "name": title,
                "legal_entity": _cell(cells, indexes, "Entidad legal"),
                "description": _cell(cells, indexes, "Descripción"),
                "date": _cell(cells, indexes, "Fecha y hora de prestación de servicios"),
                "quantity": _parse_decimal(_cell(cells, indexes, "Número")),
                "price": _parse_decimal(_cell(cells, indexes, "Precio")),
                "amount": _parse_decimal(_cell(cells, indexes, "Cantidad")),
            })

    # Tabla 2: pagos.
    if len(tables) > _PAYMENTS_TABLE:
        table = tables[_PAYMENTS_TABLE]
        indexes = _column_indexes(table)
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells or any(c.rstrip(":") == "Total" for c in cells):
                continue
            payment_no = _cell(cells, indexes, "№", "N°")
            amount = _cell(cells, indexes, "Cantidad")
            if not payment_no and not amount:
                continue
            result["payments"].append({
                "id": payment_no,
                "date": _cell(cells, indexes, "Fecha de pago"),
                "created_at": _cell(cells, indexes, "Fecha de creación"),
                "invoice_num": payment_no,
                "legal_entity": _cell(cells, indexes, "Entidad legal"),
                "description": _cell(cells, indexes, "Descripción"),
                "payment_type": _cell(cells, indexes, "Tipo"),
                "amount": _parse_decimal(amount),
                "method": _cell(cells, indexes, "Método de pago"),
                "card_number": _cell(cells, indexes, "vPOS Número de la tarjeta"),
                "card_status": _cell(cells, indexes, "vPOS Estado"),
            })

    # Tabla 7: precio por noche de la habitación. La columna central no es
    # una descripción de cargo sino el nombre de la tarifa aplicada.
    if len(tables) > _ROOM_CHARGES_TABLE:
        table = tables[_ROOM_CHARGES_TABLE]
        indexes = _column_indexes(table)
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            date = _cell(cells, indexes, "Fecha")
            rate = _cell(cells, indexes, "Precio por una noche")
            amount = _cell(cells, indexes, "Precio")
            if not (rate or amount):
                continue
            result["room_charges"].append({
                "date": date,
                "description": rate,
                "amount": _parse_decimal(amount),
            })

    return result


def _parse_decimal(val: str) -> Decimal | None:
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
        resid = _attr(item, "resid")
        status = _attr(item, "status") or "0"
        data_title = _attr(item, "data-title")

        fields: dict[str, str] = {}
        if data_title:
            decoded = html.unescape(data_title)
            tooltip_soup = BeautifulSoup(decoded, "html.parser")
            divs = tooltip_soup.find_all("div")
            if divs:
                # Primer div: "Reserva №23229 (Reservación), Venta directa"
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
            "guest_count": int(fields.get("cantidad de huéspedes", "0")) if fields.get("cantidad de huéspedes", "").isdigit() else None,
            "balance": fields.get("balance", ""),
            "phone": fields.get("teléfono", ""),
            "email": fields.get("email", ""),
            "comments": fields.get("comentarios", ""),
        })

    return reservations


def extract_guest_data(folio_html: str) -> dict:
    """Extrae datos de huésped desde HTML del folio.

    El formulario usa labels rusos: <label>Имя</label> <input value="DATA">
    Campos extraídos: first_name, last_name, middle_name, gender,
    birth_date, phone, email, country, city, language, etc.
    """
    label_map = {
        "Имя": "first_name",
        "Фамилия": "last_name",
        "Отчество": "middle_name",
        "Пол": "gender",
        "Дата рождения": "birth_date",
        "Телефон": "phone",
        "Email": "email",
        "Страна": "country",
        "Город": "city",
        "Улица": "street",
        "Дом": "house",
        "Квартира": "apartment",
        "Почтовый индекс": "postal_code",
        "Язык общения гостя": "language",
        "Категория гостя": "guest_category",
    }

    guest_data = {}
    for russ_label, en_field in label_map.items():
        # Pattern: <label>RUSSIAN</label> ... <input ... value="DATA">
        pattern = re.escape(russ_label) + r"</label>\s*<input[^>]*value=\"([^\"]*)\""
        match = re.search(pattern, folio_html)
        if match:
            value = match.group(1).strip()
            if value:
                guest_data[en_field] = value

        # For select fields (country, city)
        if not guest_data.get(en_field):
            pattern2 = re.escape(russ_label) + r"</label>\s*<select[^>]*>\s*<option[^>]*selected[^>]*>([^<]+)</option>"
            match = re.search(pattern2, folio_html)
            if match:
                guest_data[en_field] = match.group(1).strip()

    # Gender: radio button checked (value="1" for male, "2" for female)
    if not guest_data.get("gender"):
        gender_match = re.search(r'<input[^>]*name="pol2"[^>]*value="(\d)"[^>]*checked', folio_html)
        if gender_match:
            guest_data["gender"] = gender_match.group(1)

    return guest_data


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.strip())
    except (ValueError, TypeError):
        return None
