"""
Parsers para HTML extraído de OtelMS.
Convierte HTML crudo en estructuras de datos tipadas.
"""
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from bs4 import BeautifulSoup

from otelms.config.constants import ReservationStatus
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


def normalize_float(value: Optional[str]) -> Optional[float]:
    """Normaliza string a float."""
    if not value:
        return None
    try:
        # Remover símbolos de moneda, espacios
        # Manejar formato europeo: 99,99 -> 99.99
        cleaned = re.sub(r"[^\d,\.\-]", "", str(value))
        # Si hay coma y no punto, asumir que la coma es decimal
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        # Si hay ambos, eliminar comas (separadores de miles)
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def normalize_decimal(value: Optional[str]) -> Optional[Decimal]:
    """Normaliza string a Decimal."""
    if not value:
        return None
    try:
        cleaned = re.sub(r"[^\d\.\-]", "", str(value))
        return Decimal(cleaned) if cleaned else None
    except Exception:
        return None


def normalize_date(value: Optional[str]) -> Optional[str]:
    """Normaliza fecha a formato ISO (YYYY-MM-DD)."""
    if not value:
        return None
    value = str(value).strip()
    # Intentar varios formatos
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Si contiene datetime, extraer solo fecha
    dt_match = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    if dt_match:
        return dt_match.group(1)
    return None


def normalize_datetime(value: Optional[str]) -> Optional[str]:
    """Normaliza datetime a formato ISO (YYYY-MM-DDTHH:MM:SS)."""
    if not value:
        return None
    value = str(value).strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None


class CalendarParser:
    """Parser para grilla de calendario."""

    @staticmethod
    def parse_categories(html: str) -> list[dict]:
        """Parsea categorías y habitaciones desde HTML del calendario."""
        soup = BeautifulSoup(html, "lxml")
        categories = []

        table = soup.find("table", class_="calendar_table")
        if not table:
            return categories

        for cat_row in table.find_all("tr", class_="category_row"):
            cat_id = cat_row.get("data-category-id") or cat_row.get("id", "").replace("cat_", "")
            cat_name_elem = cat_row.find("td", class_="category_name") or cat_row.find("th", class_="category_name")
            cat_name = cat_name_elem.get_text(strip=True) if cat_name_elem else f"Category {cat_id}"

            rooms = []
            for room_row in cat_row.find_next_siblings("tr", class_="room_row"):
                if room_row.get("data-category-id") != cat_id:
                    break
                room_id = room_row.get("data-room-id") or room_row.get("id", "").replace("room_", "")
                room_name_elem = room_row.find("td", class_="room_name") or room_row.find("th", class_="room_name")
                room_name = room_name_elem.get_text(strip=True) if room_name_elem else f"Room {room_id}"

                rooms.append({
                    "id": room_id,
                    "name": room_name,
                    "category_id": cat_id,
                })

            categories.append({
                "id": cat_id,
                "name": cat_name,
                "rooms": rooms,
            })

        return categories

    @staticmethod
    def parse_grid(html: str, target_date: Optional[str] = None) -> dict[str, Any]:
        """Parsea grilla completa de calendario."""
        soup = BeautifulSoup(html, "lxml")

        # Extraer mapeo day_id -> date
        day_id_to_date = {}
        header_row = soup.find("tr", class_="calendar_header") or soup.find("thead")
        if header_row:
            for th in header_row.find_all("th", class_="calendar_date"):
                day_id = th.get("data-day-id")
                date_text = th.get("data-date") or th.get_text(strip=True)
                if day_id and date_text:
                    day_id_to_date[day_id] = normalize_date(date_text) or date_text

        # Obtener categorías primero
        categories = CalendarParser.parse_categories(html)
        room_to_category = {}
        for cat in categories:
            for room in cat["rooms"]:
                room_to_category[room["id"]] = {"id": cat["id"], "name": cat["name"]}

        table = soup.find("table", class_="calendar_table")
        if not table:
            return {"cells": [], "categories": categories, "day_id_to_date": day_id_to_date}

        cells = []

        for room_row in table.find_all("tr", class_="room_row"):
            room_id = room_row.get("data-room-id") or room_row.get("id", "").replace("room_", "")
            room_name_elem = room_row.find("td", class_="room_name") or room_row.find("th", class_="room_name")
            room_name = room_name_elem.get_text(strip=True) if room_name_elem else room_id

            cat_info = room_to_category.get(room_id, {"id": "", "name": ""})

            for cell in room_row.find_all("td", class_="calendar_cell"):
                day_id = cell.get("data-day-id") or cell.get("id", "").replace("cell_", "")
                cell_date = day_id_to_date.get(day_id, target_date or "")
                cell_class = cell.get("class", [])
                cell_status = "available"
                class_str = " ".join(cell_class).lower()
                if "occupied" in class_str:
                    cell_status = "occupied"
                elif "locked" in class_str:
                    cell_status = "locked"
                elif "maintenance" in class_str:
                    cell_status = "maintenance"

                cell_data = {
                    "room_id": room_id,
                    "room_name": room_name,
                    "category_id": cat_info["id"],
                    "category_name": cat_info["name"],
                    "date": cell_date,
                    "day_id": day_id,
                    "cell_status": cell_status,
                }

                if cell_status == "occupied":
                    item = cell.find("div", class_="calendar_item")
                    if item:
                        resid = item.get("resid")
                        if resid:
                            cell_data["reservation_id"] = resid
                            tooltip = item.find("div", class_="tooltip_content")
                            if tooltip:
                                CalendarParser._parse_tooltip(tooltip, cell_data)

                cells.append(cell_data)

        return {
            "cells": cells,
            "categories": categories,
            "day_id_to_date": day_id_to_date,
            "extracted_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _parse_tooltip(tooltip: BeautifulSoup, cell_data: dict) -> None:
        """Parsea tooltip y actualiza cell_data."""
        text = tooltip.get_text(" ", strip=True)

        patterns = {
            "reservation_number": r"Reserva[:\s]*(\d+)",
            "guest_name": r"Huésped[:\s]*([^<\n]+)",
            "check_in": r"Llegada[:\s]*(\d{4}-\d{2}-\d{2})",
            "check_out": r"Salida[:\s]*(\d{4}-\d{2}-\d{2})",
            "created_at": r"fecha de creación[:\s]*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})",
            "guest_count": r"Cantidad de huéspedes[:\s]*(\d+)",
            "balance": r"Balance[:\s]*([+-]?\d+\.?\d*)",
            "phone": r"Teléfono[:\s]*([^<\n]*)",
            "email": r"Email[:\s]*([^<\n]*)",
            "user": r"Usuario[:\s]*([^<\n]*)",
            "comments": r"Comentarios[:\s]*(.*?)(?:\n|$)",
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if field == "guest_count":
                    value = int(value) if value.isdigit() else None
                elif field == "balance":
                    value = normalize_float(value)
                elif field in ["check_in", "check_out", "created_at"]:
                    value = normalize_date(value) if field != "created_at" else normalize_datetime(value)
                cell_data[field] = value

        # Status
        status_match = re.search(r"(?:Reserva|Salida|Alojamiento).*?(\d)", text)
        if status_match:
            cell_data["reservation_status"] = ReservationStatus.from_text(status_match.group(0))


class ReservationDetailParser:
    """Parser para detalle de reserva (folio)."""

    @staticmethod
    def parse_basic_info(html: str) -> dict[str, Any]:
        """Parsea información básica del folio."""
        soup = BeautifulSoup(html, "lxml")
        data = {}

        # Número y status
        h2 = soup.find("h2", class_="nameofgroup")
        if h2:
            text = h2.get_text(strip=True)
            status_match = re.search(r"(Reserva|Salida|Alojamiento)", text)
            num_match = re.search(r"(\d{4,})", text)
            if status_match:
                data["status"] = ReservationStatus.from_text(status_match.group(1))
            if num_match:
                data["reservation_number"] = num_match.group(1)

        # Balance
        balance_div = soup.find("div", class_="balans")
        if balance_div:
            balance_text = balance_div.get_text(strip=True).replace("Saldo:", "").strip()
            data["balance"] = normalize_float(balance_text)

        # Campos clave-valor
        fields_map = {}
        for label in soup.find_all("span", class_="incolor"):
            key = label.get_text(strip=True)
            parent = label.find_parent("div")
            if not parent:
                continue
            value_div = parent.find_next_sibling("div", class_="text-right")
            if value_div:
                img = value_div.find("img")
                if img and "dc_logo" in img.get("src", ""):
                    fields_map[key] = "booking"
                else:
                    fields_map[key] = " ".join(value_div.stripped_strings)

        data["fields"] = fields_map

        # Mapear campos conocidos
        field_mapping = {
            "Huésped": "guest_name",
            "Fuente": "source",
            "Llegada": "check_in",
            "Salida": "check_out",
            "Teléfono": "phone",
            "e-mail": "email",
            "Notas": "comments",
            "Usuario": "user",
            "Total": "total",
            "Pagado": "paid",
            "Balance": "balance",
            "Número de huéspedes": "guest_count",
            "Tipo de habitación": "room_type",
            "Habitación": "room",
            "Tarifa": "rate",
        }

        for label, value in fields_map.items():
            field = field_mapping.get(label)
            if field:
                if field in ["total", "paid", "balance", "rate"]:
                    data[field] = normalize_float(value)
                elif field in ["guest_count"]:
                    data[field] = int(value.split()[0]) if value and value.split()[0].isdigit() else None
                elif field in ["check_in", "check_out"]:
                    data[field] = normalize_date(value)
                else:
                    data[field] = value

        # Lista de huéspedes
        guest_label = soup.find("span", class_="incolor", string="Lista de huéspedes")
        if guest_label:
            parent = guest_label.find_parent("div")
            if parent:
                guest_div = parent.find_next_sibling("div", class_="text-right")
                if guest_div:
                    data["guest_list"] = list(guest_div.stripped_strings)

        return data

    @staticmethod
    def parse_accommodation_modal(html: str) -> dict[str, Any]:
        """Parsea modal de edición de alojamiento."""
        soup = BeautifulSoup(html, "lxml")
        data = {}

        # Campos del formulario
        for field_group in soup.find_all("div", class_="form-group"):
            label = field_group.find("label", class_="control-label")
            if not label:
                continue
            key = label.get_text(strip=True).lower().replace(" ", "_").replace(":", "")
            input_elem = field_group.find("input", class_="form-control") or field_group.find("select", class_="form-control")
            if input_elem:
                data[key] = input_elem.get("value") or input_elem.get_text(strip=True)

        return data


class GuestDetailParser:
    """Parser para detalle de huésped."""

    @staticmethod
    def parse(html: str) -> dict[str, Any]:
        """Parsea datos del huésped."""
        soup = BeautifulSoup(html, "lxml")
        data = {}

        # ID del header
        header = soup.find("span", class_="header-time")
        if header:
            text = header.get_text(" ", strip=True)
            match = re.search(r"ID:\s*(\d+)", text)
            if match:
                data["id"] = match.group(1)

        # Panel "Tarjeta de huésped"
        panel = None
        for p in soup.find_all("div", class_="panel"):
            heading = p.find("div", class_="panel-heading")
            if heading and "Tarjeta de huésped" in heading.get_text():
                panel = p
                break

        if not panel:
            panel = soup.find("div", {"data-widget": lambda x: x and "wiget1" in x})

        if panel:
            body = panel.find("div", class_="panel-body")
            if body:
                container = body.find("div", class_="folio1") or body
                cols = container.find_all("div", class_="col-md-2")

                for col in cols:
                    b_tag = col.find("b")
                    if not b_tag:
                        continue

                    key = b_tag.get_text(strip=True).rstrip(":").lower()
                    val = ""
                    curr = b_tag.next_sibling
                    while curr:
                        if isinstance(curr, str):
                            val += curr
                        elif curr.name == "br":
                            pass
                        else:
                            val += curr.get_text(" ", strip=True)
                        curr = curr.next_sibling

                    val = val.strip()
                    data[key] = val

        # Normalizar campos conocidos
        field_map = {
            "nombre": "first_name",
            "apellido": "last_name",
            "segundo nombre": "middle_name",
            "género": "gender",
            "fecha de nacimiento": "dob",
            "teléfono": "phone",
            "email": "email",
            "lenguaje": "language",
            "país": "country",
            "ciudad": "city",
            "calle": "street",
            "casa": "house",
            "código postal": "zip_code",
            "tipo de documento": "document_type",
            "documento número": "document_number",
            "número de documento": "document_number",
            "fecha de emisión": "issue_date",
            "validez": "expiration_date",
            "emitido por": "issued_by",
        }

        normalized = {}
        for k, v in data.items():
            new_key = field_map.get(k, k)
            if new_key == "dob":
                v = normalize_date(v)
            normalized[new_key] = v

        # Construir nombre completo
        parts = [normalized.get("first_name"), normalized.get("middle_name"), normalized.get("last_name")]
        full_name = " ".join([p for p in parts if p])
        if full_name:
            normalized["name"] = full_name

        return normalized


class ModalParser:
    """Parser para modales de reserva."""

    @staticmethod
    def parse(html: str, reservation_id: Optional[str] = None) -> dict[str, Any]:
        """Parsea modal de reserva."""
        soup = BeautifulSoup(html, "lxml")
        data = {}

        # Número de reserva y status
        h2 = soup.find("h2", class_="nameofgroup") or soup.find("h2")
        if h2:
            text = h2.get_text(strip=True)
            match = re.findall(r"(?:Reserva|Salida|Alojamiento)|\d+", text)
            if len(match) >= 2:
                data["status"] = ReservationStatus.from_text(match[0].strip())
                data["reservation_number"] = match[1]
            elif reservation_id:
                data["reservation_number"] = reservation_id

        # Balance
        balance_div = soup.find("div", class_="balans")
        if balance_div:
            balance_text = balance_div.get_text(strip=True).replace("Saldo:", "").strip()
            data["balance"] = normalize_float(balance_text)

        # Campos
        fields_map = {}
        for label in soup.find_all("span", class_="incolor"):
            key = label.get_text(strip=True)
            parent = label.find_parent("div")
            if not parent:
                continue
            value_div = parent.find_next_sibling("div", class_="text-right")
            if value_div:
                img = value_div.find("img")
                if img and "dc_logo" in img.get("src", ""):
                    fields_map[key] = "booking"
                else:
                    fields_map[key] = " ".join(value_div.stripped_strings)

        data["fields"] = fields_map

        # Mapear
        field_mapping = {
            "Huésped": "guest_name",
            "Fuente": "source",
            "Llegada": "check_in",
            "Salida": "check_out",
            "Teléfono": "phone",
            "e-mail": "email",
            "Notas": "comments",
            "Usuario": "user",
            "Total": "total",
            "Pagado": "paid",
            "Balance": "balance",
            "Número de huéspedes": "guest_count",
            "Tipo de habitación": "room_type",
            "Habitación": "room",
            "Tarifa": "rate",
        }

        for label, value in fields_map.items():
            field = field_mapping.get(label)
            if field:
                if field in ["total", "paid", "balance", "rate"]:
                    data[field] = normalize_float(value)
                elif field == "guest_count":
                    data[field] = int(value.split()[0]) if value and value.split()[0].isdigit() else None
                elif field in ["check_in", "check_out"]:
                    data[field] = normalize_date(value)
                else:
                    data[field] = value

        # Lista de huéspedes
        guest_label = soup.find("span", class_="incolor", string="Lista de huéspedes")
        if guest_label:
            parent = guest_label.find_parent("div")
            if parent:
                guest_div = parent.find_next_sibling("div", class_="text-right")
                if guest_div:
                    data["guest_list"] = list(guest_div.stripped_strings)

        # Buscar habitación/tipo en campos
        for key, value in fields_map.items():
            if "habitación" in key.lower():
                data["room"] = value
            if "tipo" in key.lower():
                data["room_type"] = value
            if "cread" in key.lower():
                data["created_at"] = normalize_datetime(value)

        return data


class AllModalsParser:
    """Parser para múltiples modales."""

    @staticmethod
    def parse_all(modals_html: dict[str, str]) -> list[dict]:
        """Parsea todos los modales."""
        results = []
        for res_id, html in modals_html.items():
            try:
                parsed = ModalParser.parse(html, reservation_id=res_id)
                results.append(parsed)
            except Exception as e:
                logger.warning("Error parsing modal", reservation_id=res_id, error=str(e))
        return results