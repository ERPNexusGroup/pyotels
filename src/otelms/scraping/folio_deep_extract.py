"""
Extractor y parser exhaustivo del Folio de Reserva (/reservation_c2/folio/{id}/1).
Extrae todos los componentes requeridos:
- Datos del cliente: nombre, teléfono, email, pagador, entidad legal
- Fuente / Canal de venta (Venta directa, Booking, Expedia, etc.)
- Fechas y estancia: check-in, check-out, noches, habitación, categoría, tarifa
- Cantidad de huéspedes (adultos, niños, bebés)
- Vehículo (marca, color, matrícula)
- Notas de la reserva
- Información transmitida desde el canal (OTA reservation ID, detalles)
- Tarifa asignada por día (desglose noche a noche)
- Servicios y consumos realizados
- Pagos registrados
- Historial completo de cambios / auditoría (usuario, fecha, acción, descripción)
"""
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import settings
from otelms.scraping.auth import get_authenticated_http_session
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


def parse_folio_complete(html_content: str, reservation_id: str | int) -> dict[str, Any]:
    """Parsea exhaustivamente todo el documento HTML del folio de reserva."""
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")

    # Identificación y estado
    nameofgroup = soup.find(class_="nameofgroup")
    status_text = ""
    res_num = str(reservation_id)
    if nameofgroup:
        full_title = nameofgroup.get_text(strip=True)
        m = re.search(r"(Reserva|Alojamiento|Salida|Check.?in|Check.?out|Cancelad[ao]|No.?show)\s*[-–—]?\s*№?(\d+)?", full_title, re.I)
        if m:
            status_text = m.group(1).strip()
            if m.group(2):
                res_num = m.group(2).strip()

    # Saldo / Balance
    balans_elem = soup.find(class_="balans")
    balance_str = ""
    if balans_elem:
        balance_str = balans_elem.get_text(strip=True).replace("Saldo:", "").replace("Balance:", "").strip()

    # Mapeo de campos en paneles
    basic_info: dict[str, Any] = {}
    stay_info: dict[str, Any] = {}
    channel_info: dict[str, Any] = {}

    for panel in soup.find_all("div", class_="panel"):
        heading = panel.find(class_="panel-heading")
        heading_text = heading.get_text(strip=True).lower() if heading else ""

        # Panel: Información básica
        if "básica" in heading_text or "basica" in heading_text:
            text = panel.get_text(" | ", strip=True)
            # Buscar Cliente / Huésped
            m_client = re.search(r"(?:Cliente|Huésped):\s*\|\s*([^|]+)", text)
            if m_client:
                basic_info["client_name"] = m_client.group(1).strip()
                basic_info["name"] = basic_info["client_name"]
            m_phone = re.search(r"Teléfono:\s*\|\s*([^|]+)", text)
            if m_phone:
                val = m_phone.group(1).strip()
                if not val.startswith("Email"):
                    basic_info["phone"] = val
            m_email = re.search(r"(?:Email|Correo electrónico|Correo):\s*\|\s*([^|]+)", text)
            if m_email:
                val = m_email.group(1).strip()
                if not val.startswith("Pagador"):
                    basic_info["email"] = val
            m_legal = re.search(r"Entidad legal:\s*\|\s*([^|]+)", text)
            if m_legal:
                basic_info["legal_entity"] = m_legal.group(1).strip()
            m_source = re.search(r"Fuente:\s*\|\s*([^|]+)", text)
            if m_source:
                basic_info["source"] = m_source.group(1).strip()

        # Panel: Alojamiento
        elif "alojamiento" in heading_text or "estancia" in heading_text:
            text = panel.get_text(" | ", strip=True)
            m_dates = re.search(r"Período de estancia:\s*\|\s*([\d-]+ [\d:]+)\s*\|\s*([\d-]+ [\d:]+)", text)
            if m_dates:
                stay_info["check_in"] = m_dates.group(1).strip()
                stay_info["check_out"] = m_dates.group(2).strip()
            m_nights = re.search(r"Noches:\s*\|\s*(\d+)", text)
            if m_nights:
                stay_info["nights"] = int(m_nights.group(1))
            m_room = re.search(r"Habitación:\s*\|\s*([^|]+)\s*\|\s*([^|]+)", text)
            if m_room:
                stay_info["room_number"] = m_room.group(1).strip()
                stay_info["category_name"] = m_room.group(2).strip()
            m_guests = re.search(r"Huéspedes:\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)", text)
            if m_guests:
                stay_info["adults"] = int(m_guests.group(1))
                stay_info["children"] = int(m_guests.group(2))
                stay_info["babies"] = int(m_guests.group(3))
            m_rate = re.search(r"Tarifa:\s*\|\s*([^|]+)", text)
            if m_rate:
                stay_info["rate_name"] = m_rate.group(1).strip()
                stay_info["rate"] = stay_info["rate_name"]

        # Panel: Información desde el canal
        elif "canal" in heading_text or "channel" in heading_text:
            text = panel.get_text(" | ", strip=True)
            m_res_id = re.search(r"(?:Reservation ID|ID de reserva en OTA|ID de reserva):\s*\|\s*([^|]+)", text, re.I)
            if m_res_id:
                channel_info["channel_reservation_id"] = m_res_id.group(1).strip("[] ")
            m_room_res = re.search(r"(?:Room reservation ID|ID de reserva de habitación):\s*\|\s*([^|]+)", text, re.I)
            if m_room_res:
                channel_info["room_reservation_id"] = m_room_res.group(1).strip()
            m_ch_guest = re.search(r"Nombre de huésped:\s*\|\s*([^|]+)", text)
            if m_ch_guest:
                channel_info["channel_guest_name"] = m_ch_guest.group(1).strip()
            m_ch_phone = re.search(r"Teléfono de huésped:\s*\|\s*([^|]+)", text)
            if m_ch_phone:
                channel_info["channel_phone"] = m_ch_phone.group(1).strip()
            m_ch_amount = re.search(r"Monto del pago:\s*\|\s*([^|]+)", text)
            if m_ch_amount:
                channel_info["channel_payment_amount"] = m_ch_amount.group(1).strip()

    # Identificar tablas por cabeceras
    def _headers(tbl: Any) -> list[str]:
        return [th.get_text(strip=True).lower() for th in tbl.find_all("th")]

    tbl_guests = None
    tbl_services = None
    tbl_payments = None
    tbl_vehicle = None
    tbl_notes = None
    tbl_rates = None
    tbl_history = None

    for tbl in tables:
        hdrs = _headers(tbl)
        hdr_str = " ".join(hdrs)
        if any(w in hdr_str for w in ["marca", "color", "matrícula", "matricula"]):
            tbl_vehicle = tbl
        elif any(w in hdr_str for w in ["autor", "texto", "comentario", "nota"]):
            tbl_notes = tbl
        elif any(w in hdr_str for w in ["tarifa base", "precio por una noche", "tarifa"]):
            tbl_rates = tbl
        elif any(w in hdr_str for w in ["usuario", "acción", "accion", "detalles"]):
            tbl_history = tbl
        elif any(w in hdr_str for w in ["método", "metodo", "vpos", "fecha de pago"]):
            tbl_payments = tbl
        elif any(w in hdr_str for w in ["prestación", "prestacion", "título", "titulo", "servicio"]):
            tbl_services = tbl
        elif any(w in hdr_str for w in ["huésped", "huesped", "adultos"]):
            tbl_guests = tbl

    # Fallbacks posicionales si alguna no se reconoció por cabecera
    if not tbl_guests and len(tables) > 0:
        tbl_guests = tables[0]
    if not tbl_services and len(tables) > 1:
        tbl_services = tables[1]
    if not tbl_payments and len(tables) > 2:
        tbl_payments = tables[2]
    if not tbl_vehicle and len(tables) > 5:
        tbl_vehicle = tables[5]
    if not tbl_notes and len(tables) > 6:
        tbl_notes = tables[6]
    if not tbl_rates and len(tables) > 7:
        tbl_rates = tables[7]
    if not tbl_history and len(tables) > 9:
        tbl_history = tables[9]

    # 1. Huéspedes
    guests_list: list[dict[str, Any]] = []
    if tbl_guests:
        for tr in tbl_guests.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                guests_list.append({
                    "name": cells[0],
                    "gender": cells[1] if len(cells) > 1 else "",
                    "email": cells[2] if len(cells) > 2 else "",
                    "birth_date": cells[3] if len(cells) > 3 else "",
                    "nationality": cells[5] if len(cells) > 5 else "",
                })

    # 2. Servicios / Cargos
    services_list: list[dict[str, Any]] = []
    if tbl_services:
        for tr in tbl_services.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or "Total:" in cells:
                continue
            if len(cells) >= 3 and any(cells):
                from decimal import Decimal
                clean_p = re.sub(r"[^\d.]", "", cells[6].replace(",", ".")) if len(cells) > 6 else ""
                clean_amt = re.sub(r"[^\d.]", "", cells[7].replace(",", ".")) if len(cells) > 7 else ""
                services_list.append({
                    "date": cells[0],
                    "id": cells[1] if len(cells) > 1 else "",
                    "title": cells[2] if len(cells) > 2 else "",
                    "legal_entity": cells[3] if len(cells) > 3 else "",
                    "description": cells[4] if len(cells) > 4 else "",
                    "quantity": cells[5] if len(cells) > 5 else "1",
                    "price": Decimal(clean_p) if clean_p else Decimal("0"),
                    "total": Decimal(clean_amt or clean_p) if (clean_amt or clean_p) else Decimal("0"),
                    "amount": Decimal(clean_amt or clean_p) if (clean_amt or clean_p) else Decimal("0"),
                })

    # 3. Pagos
    payments_list: list[dict[str, Any]] = []
    if tbl_payments:
        for tr in tbl_payments.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or "Total:" in cells:
                continue
            if len(cells) >= 6 and cells[0]:
                from decimal import Decimal
                clean_amt = re.sub(r"[^\d.]", "", cells[6].replace(",", ".")) if len(cells) > 6 else ""
                payments_list.append({
                    "date": cells[0],
                    "created_at": cells[1] if len(cells) > 1 else "",
                    "id": cells[2] if len(cells) > 2 else "",
                    "legal_entity": cells[3] if len(cells) > 3 else "",
                    "description": cells[4] if len(cells) > 4 else "",
                    "type": cells[5] if len(cells) > 5 else "",
                    "amount": Decimal(clean_amt) if clean_amt else Decimal("0"),
                    "method": cells[7] if len(cells) > 7 else "",
                    "card_status": cells[9] if len(cells) > 9 else "",
                })

    # 4. Vehículo
    vehicle: dict[str, str] | None = None
    if tbl_vehicle:
        v_rows = tbl_vehicle.find_all("tr")[1:]
        if v_rows:
            v_cells = [td.get_text(strip=True) for td in v_rows[0].find_all(["td", "th"])]
            if len(v_cells) >= 3 and any(v_cells[:3]):
                vehicle = {
                    "brand": v_cells[0],
                    "color": v_cells[1],
                    "license_plate": v_cells[2],
                    "plate": v_cells[2],
                }

    # 5. Notas
    notes_list: list[dict[str, str]] = []
    if tbl_notes:
        for tr in tbl_notes.find_all("tr")[1:]:
            n_cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(n_cells) >= 3 and any(n_cells[:3]):
                notes_list.append({
                    "date": n_cells[0],
                    "user": n_cells[1],
                    "author": n_cells[1],
                    "note": n_cells[2],
                    "text": n_cells[2],
                })

    # 6. Tarifa asignada por día / Noches
    night_rates: list[dict[str, Any]] = []
    if tbl_rates:
        for tr in tbl_rates.find_all("tr")[1:]:
            r_cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(r_cells) >= 3 and r_cells[0]:
                from decimal import Decimal
                clean_r = re.sub(r"[^\d.]", "", r_cells[2].replace(",", "."))
                night_rates.append({
                    "date": r_cells[0],
                    "rate_name": r_cells[1],
                    "price": r_cells[2],
                    "amount": Decimal(clean_r) if clean_r else Decimal("0"),
                    "currency": "USD",
                })

    # 7. Historial de cambios / Auditoría
    change_history: list[dict[str, str]] = []
    if tbl_history:
        for tr in tbl_history.find_all("tr")[1:]:
            h_cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(h_cells) >= 4 and h_cells[0]:
                change_history.append({
                    "datetime": h_cells[0],
                    "date": h_cells[0],
                    "id": h_cells[1] if len(h_cells) > 5 else "",
                    "user": h_cells[2] if len(h_cells) > 5 else h_cells[1],
                    "action": h_cells[4] if len(h_cells) > 5 else h_cells[2],
                    "details": h_cells[6] if len(h_cells) > 6 else h_cells[-1],
                })

    if stay_info.get("room_number") or stay_info.get("category_name"):
        stay_info["room_name"] = f"{stay_info.get('room_number', '')} {stay_info.get('category_name', '')}".strip()

    return {
        "reservation_id": res_num,
        "status": status_text,
        "balance": balance_str,
        "basic": basic_info,
        "client": basic_info,
        "stay": stay_info,
        "channel": channel_info,
        "channel_data": channel_info,
        "guests": guests_list,
        "vehicle": vehicle,
        "notes": notes_list,
        "night_rates": night_rates,
        "services": services_list,
        "payments": payments_list,
        "change_history": change_history,
    }


class FolioDeepExtractor:
    """Cliente HTTP para extracción profunda de folios de reserva."""

    def __init__(
        self,
        hotel_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_domain: str = "otelms.com",
    ):
        self.hotel_id = hotel_id or settings.otelms_default_hotel_id
        self.base_domain = base_domain
        self.urls = OtelMSUrls(base_domain, self.hotel_id)
        self._client = client
        self._own_client = False

    async def __aenter__(self) -> "FolioDeepExtractor":
        if self._client is None:
            self._client = await get_authenticated_http_session(self.hotel_id)
            self._own_client = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = await get_authenticated_http_session(self.hotel_id)
            self._own_client = True
        return self._client

    async def get_reservation_folio(self, reservation_id: str | int) -> dict[str, Any]:
        """Descarga y parsea completamente el folio de una reserva."""
        client = await self._ensure_client()
        url = self.urls.reservation_detail_url(str(reservation_id))
        resp = await client.get(url)
        return parse_folio_complete(resp.text, str(reservation_id))
