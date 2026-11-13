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
import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import settings
from otelms.scraping.auth import get_authenticated_http_session
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

_EMPTY_MARKERS = {"", "0", "---", "–", "—", "n/a", "na", "none", "null"}


def _normalize_optional(value: Any) -> str | None:
    """Convierte literales vacíos/placeholder a None."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        # 0 numérico se conserva salvo que venga como marcador textual explícito
        return str(value)
    text = str(value).strip()
    if text.lower() in _EMPTY_MARKERS:
        return None
    # Etiquetas capturadas por error en paneles (ej. siguiente label)
    if text.endswith(":") and len(text) < 60:
        return None
    return text


def _panel_rows(panel: Tag) -> dict[str, str]:
    """Extrae pares label->valor desde filas DOM (tr/td/th o divs label/valor)."""
    out: dict[str, str] = {}
    # Preferir filas de tabla dentro del panel
    for tr in panel.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True).rstrip(":").lower()
            value = cells[1].get_text(" ", strip=True)
            if label:
                out[label] = value
    if out:
        return out
    # Fallback: pares consecutivos de nodos de texto/elementos (label, value)
    texts = [el.get_text(" ", strip=True) for el in panel.find_all(["dt", "dd", "label", "span", "div"], recursive=True)]
    # intento simple por ":" en textos planos si no hay estructura
    if not out:
        for line in panel.stripped_strings:
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().lower()
                if k:
                    out.setdefault(k, v.strip())
    return out


def _panel_get(rows: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        key = label.lower().rstrip(":")
        if key in rows:
            val = rows[key].strip()
            return val if val != "" else None
        # búsqueda por inclusión para etiquetas con variaciones
        for k, v in rows.items():
            if key in k:
                vv = v.strip()
                return vv if vv != "" else None
    return None


def _parse_decimal(val: str | None) -> Decimal:
    if not val:
        return Decimal("0")
    clean = re.sub(r"[^\d,.-]", "", str(val)).replace(",", ".")
    if clean in {"", ".", "-", "-."}:
        return Decimal("0")
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_decimal_optional(val: str | None) -> Decimal | None:
    if val is None:
        return None
    text = str(val).strip()
    if text == "" or text.lower() in {"---", "–", "—", "n/a", "na", "none", "null"}:
        return None
    clean = re.sub(r"[^\d,.-]", "", text).replace(",", ".")
    if clean in {"", ".", "-", "-."}:
        return None
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return None


def _headers(tbl: Tag) -> list[str]:
    head = tbl.find("tr")
    if not head:
        return []
    return [c.get_text(" ", strip=True).lower() for c in head.find_all(["th", "td"])]


def _col_idx(headers: list[str], *names: str) -> int | None:
    for i, h in enumerate(headers):
        for n in names:
            if n.lower() in h:
                return i
    return None


def _cell_text(cells: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx]


def parse_folio_complete(html_content: str, reservation_id: str | int) -> dict[str, Any]:
    """Parsea exhaustivamente todo el documento HTML del folio de reserva."""
    soup = BeautifulSoup(html_content, "html.parser")
    # Tablas de datos del folio (excluir tablas dentro de paneles informativos)
    data_tables: list[Tag] = []
    for tbl in soup.find_all("table"):
        if tbl.find_parent("div", class_="panel"):
            continue
        data_tables.append(tbl)
    tables = data_tables or soup.find_all("table")

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

    # Mapeo de campos en paneles (DOM-based)
    basic_info: dict[str, Any] = {}
    stay_info: dict[str, Any] = {}
    channel_info: dict[str, Any] = {}

    for panel in soup.find_all("div", class_="panel"):
        heading = panel.find(class_="panel-heading")
        heading_text = heading.get_text(strip=True).lower() if heading else ""
        rows = _panel_rows(panel)

        # Panel: Información básica
        if "básica" in heading_text or "basica" in heading_text:
            client = _normalize_optional(_panel_get(rows, "cliente", "huésped", "huesped"))
            if client:
                basic_info["client_name"] = client
                basic_info["name"] = client
            phone = _normalize_optional(_panel_get(rows, "teléfono", "telefono"))
            if phone:
                basic_info["phone"] = phone
            email = _normalize_optional(_panel_get(rows, "email", "correo electrónico", "correo electronico", "correo"))
            if email:
                basic_info["email"] = email
            legal = _normalize_optional(_panel_get(rows, "entidad legal", "pagador"))
            if legal:
                basic_info["legal_entity"] = legal
            source = _normalize_optional(_panel_get(rows, "fuente"))
            if source:
                basic_info["source"] = source

        # Panel: Alojamiento
        elif "alojamiento" in heading_text or "estancia" in heading_text:
            # Período puede venir en dos celdas o en texto
            period = _panel_get(rows, "período de estancia", "periodo de estancia")
            if period:
                dates = re.findall(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?", period)
                if len(dates) >= 2:
                    stay_info["check_in"] = dates[0]
                    stay_info["check_out"] = dates[1]
            if "check_in" not in stay_info or "check_out" not in stay_info:
                # intentar por celdas específicas si existen
                ci = _panel_get(rows, "llegada", "check-in", "check in")
                co = _panel_get(rows, "salida", "check-out", "check out")
                if ci and "check_in" not in stay_info:
                    stay_info["check_in"] = ci
                if co and "check_out" not in stay_info:
                    stay_info["check_out"] = co
            nights = _panel_get(rows, "noches")
            if nights and str(nights).isdigit():
                stay_info["nights"] = int(nights)
            room = _panel_get(rows, "habitación", "habitacion")
            if room:
                parts = [p.strip() for p in re.split(r"\s{2,}|\s*\|\s*", room) if p.strip()]
                if parts:
                    stay_info["room_number"] = parts[0]
                if len(parts) > 1:
                    stay_info["category_name"] = parts[1]
                elif " - " in room:
                    a, b = room.split(" - ", 1)
                    stay_info["room_number"] = a.strip()
                    stay_info["category_name"] = b.strip()
            guests = _panel_get(rows, "huéspedes", "huespedes")
            if guests:
                nums = re.findall(r"\d+", guests)
                if len(nums) >= 3:
                    stay_info["adults"] = int(nums[0])
                    stay_info["children"] = int(nums[1])
                    stay_info["babies"] = int(nums[2])
            rate = _normalize_optional(_panel_get(rows, "tarifa"))
            if rate:
                stay_info["rate_name"] = rate
                stay_info["rate"] = rate

        # Panel: Información desde el canal
        elif "canal" in heading_text or "channel" in heading_text:
            ch_res = _normalize_optional(_panel_get(rows, "id de reserva en ota", "id de reserva", "reservation id"))
            if ch_res:
                channel_info["channel_reservation_id"] = ch_res.strip("[] ")
            room_res = _normalize_optional(_panel_get(rows, "id de reserva de habitación", "id de reserva de habitacion", "room reservation id"))
            if room_res:
                channel_info["room_reservation_id"] = room_res
            ch_guest = _normalize_optional(_panel_get(rows, "nombre de huésped", "nombre de huesped"))
            if ch_guest:
                channel_info["channel_guest_name"] = ch_guest
            ch_phone = _normalize_optional(_panel_get(rows, "teléfono de huésped", "telefono de huesped"))
            if ch_phone:
                channel_info["channel_phone"] = ch_phone
            ch_amount = _normalize_optional(_panel_get(rows, "monto del pago"))
            if ch_amount:
                channel_info["channel_payment_amount"] = ch_amount

    # Normalizaciones finales solicitadas
    for key in ("channel_reservation_id", "room_reservation_id"):
        if key in channel_info:
            channel_info[key] = _normalize_optional(channel_info[key])

    # Notas globales (si existen como campo en paneles; se complementa con tabla)
    notes_text: str | None = None

    # Identificar tablas por cabeceras
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
        elif any(w in hdr_str for w in ["tarifa base", "precio por una noche"]):
            tbl_rates = tbl
        elif ("usuario" in hdr_str and ("acción" in hdr_str or "accion" in hdr_str)) or ("tipo" in hdr_str and "descripción" in hdr_str):
            tbl_history = tbl
        elif any(w in hdr_str for w in ["método", "metodo", "vpos", "fecha de pago", "fecha creación pago"]):
            tbl_payments = tbl
        elif any(w in hdr_str for w in ["prestación", "prestacion", "título", "titulo", "servicio", "cargo"]):
            tbl_services = tbl
        elif any(w in hdr_str for w in ["huésped", "huesped", "adultos", "género", "genero", "nacionalidad"]):
            tbl_guests = tbl

    # Fallbacks posicionales si alguna no se reconoció por cabecera (solo tablas de datos)
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
    # Seguridad: no reutilizar la misma tabla para roles distintos
    assigned = [t for t in [tbl_guests, tbl_services, tbl_payments, tbl_vehicle, tbl_notes, tbl_rates, tbl_history] if t is not None]
    if len([id(t) for t in assigned]) != len({id(t) for t in assigned}):
        # en caso de colisión por fallback, preferir detección por cabecera (ya hecha) y limpiar duplicados obvios
        seen_ids: set[int] = set()
        for name in ("tbl_guests","tbl_services","tbl_payments","tbl_vehicle","tbl_notes","tbl_rates","tbl_history"):
            tbl = locals().get(name)
            if tbl is None:
                continue
            tid = id(tbl)
            if tid in seen_ids:
                locals()[name] = None
            else:
                seen_ids.add(tid)
        tbl_guests = locals().get("tbl_guests")
        tbl_services = locals().get("tbl_services")
        tbl_payments = locals().get("tbl_payments")
        tbl_vehicle = locals().get("tbl_vehicle")
        tbl_notes = locals().get("tbl_notes")
        tbl_rates = locals().get("tbl_rates")
        tbl_history = locals().get("tbl_history")

    # 1. Huéspedes
    guests_list: list[dict[str, Any]] = []
    if tbl_guests:
        hdrs = _headers(tbl_guests)
        i_name = _col_idx(hdrs, "huésped", "huesped", "nombre")
        i_gender = _col_idx(hdrs, "género", "genero", "sexo")
        i_email = _col_idx(hdrs, "email", "correo")
        i_birth = _col_idx(hdrs, "nacimiento", "birth")
        i_nationality = _col_idx(hdrs, "nacionalidad", "país", "pais")
        for tr in tbl_guests.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or not any(cells):
                continue
            guests_list.append({
                "name": _cell_text(cells, i_name) or (cells[0] if cells else ""),
                "gender": _cell_text(cells, i_gender) or (cells[1] if len(cells) > 1 else ""),
                "email": _cell_text(cells, i_email) or (cells[2] if len(cells) > 2 else ""),
                "birth_date": _cell_text(cells, i_birth) or (cells[3] if len(cells) > 3 else ""),
                "nationality": _cell_text(cells, i_nationality) or (cells[5] if len(cells) > 5 else ""),
            })

    # 2. Servicios / Cargos (mapeo por cabecera)
    services_list: list[dict[str, Any]] = []
    if tbl_services:
        hdrs = _headers(tbl_services)
        i_date = _col_idx(hdrs, "fecha")
        i_id = _col_idx(hdrs, "№", "n°", "no", "id")
        i_title = _col_idx(hdrs, "título", "titulo", "prestación", "prestacion", "servicio")
        i_legal = _col_idx(hdrs, "entidad legal")
        i_desc = _col_idx(hdrs, "descripción", "descripcion")
        i_qty = _col_idx(hdrs, "número", "numero", "cantidad de", "unidades")
        i_price = _col_idx(hdrs, "precio")
        i_amount = _col_idx(hdrs, "cantidad", "importe", "total", "monto")
        for tr in tbl_services.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not cells:
                continue
            joined = " ".join(cells).lower()
            if "total" in joined and (cells[0].strip().lower().startswith("total") or "total:" in joined):
                continue
            date_v = _cell_text(cells, i_date)
            title_v = _cell_text(cells, i_title) or (cells[2] if len(cells) > 2 else "")
            if not any(cells):
                continue
            price_d = _parse_decimal(_cell_text(cells, i_price) or None)
            amount_d = _parse_decimal(_cell_text(cells, i_amount) or None)
            if amount_d == Decimal("0") and price_d != Decimal("0"):
                amount_d = price_d
            services_list.append({
                "date": date_v,
                "id": _cell_text(cells, i_id) or (cells[1] if len(cells) > 1 else ""),
                "title": title_v,
                "name": title_v,
                "legal_entity": _cell_text(cells, i_legal) or (cells[3] if len(cells) > 3 else ""),
                "description": _cell_text(cells, i_desc) or (cells[4] if len(cells) > 4 else ""),
                "quantity": _cell_text(cells, i_qty) or (cells[5] if len(cells) > 5 else "1"),
                "price": price_d,
                "total": amount_d,
                "amount": amount_d,
            })

    # 3. Pagos (mapeo por cabecera)
    payments_list: list[dict[str, Any]] = []
    if tbl_payments:
        hdrs = _headers(tbl_payments)
        i_pdate = _col_idx(hdrs, "fecha de pago", "fecha")
        i_cdate = _col_idx(hdrs, "fecha de creación", "fecha creaci", "fecha creacion")
        i_pid = _col_idx(hdrs, "№", "n°", "no", "id")
        i_plegal = _col_idx(hdrs, "entidad legal", "entidad")
        i_pdesc = _col_idx(hdrs, "descripción", "descripcion")
        i_ptype = _col_idx(hdrs, "tipo")
        i_pamt = _col_idx(hdrs, "cantidad", "importe", "monto")
        i_pmethod = _col_idx(hdrs, "método", "metodo")
        i_pvpos = _col_idx(hdrs, "vpos estado", "estado")
        for tr in tbl_payments.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not cells:
                continue
            joined = " ".join(cells).lower()
            if "total" in joined and (cells[0].strip().lower().startswith("total") or "total:" in joined or any(c.strip().lower().startswith("total") for c in cells)):
                continue
            date_v = _cell_text(cells, i_pdate) or (cells[0] if len(cells) > 0 else "")
            amount_v = _cell_text(cells, i_pamt) or (cells[6] if len(cells) > 6 else "")
            if not date_v and not amount_v:
                continue
            payments_list.append({
                "date": date_v,
                "created_at": _cell_text(cells, i_cdate) or (cells[1] if len(cells) > 1 else ""),
                "id": _cell_text(cells, i_pid) or (cells[2] if len(cells) > 2 else ""),
                "legal_entity": _cell_text(cells, i_plegal) or (cells[3] if len(cells) > 3 else ""),
                "description": _cell_text(cells, i_pdesc) or (cells[4] if len(cells) > 4 else ""),
                "type": _cell_text(cells, i_ptype) or (cells[5] if len(cells) > 5 else ""),
                "amount": _parse_decimal(amount_v or None),
                "method": _cell_text(cells, i_pmethod) or (cells[7] if len(cells) > 7 else ""),
                "card_status": _cell_text(cells, i_pvpos) or (cells[9] if len(cells) > 9 else ""),
            })

    # 4. Vehículo
    vehicle: dict[str, str] | None = None
    if tbl_vehicle:
        v_rows = tbl_vehicle.find_all("tr")[1:]
        if v_rows:
            v_cells = [td.get_text(" ", strip=True) for td in v_rows[0].find_all(["td", "th"])]
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
        hdrs = _headers(tbl_notes)
        i_nd = _col_idx(hdrs, "fecha")
        i_nu = _col_idx(hdrs, "autor", "usuario")
        i_nt = _col_idx(hdrs, "texto", "nota", "comentario")
        for tr in tbl_notes.find_all("tr")[1:]:
            n_cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not n_cells or not any(n_cells):
                continue
            text = _cell_text(n_cells, i_nt) or (n_cells[2] if len(n_cells) >= 3 else "")
            user = _cell_text(n_cells, i_nu) or (n_cells[1] if len(n_cells) >= 2 else "")
            date_v = _cell_text(n_cells, i_nd) or (n_cells[0] if n_cells else "")
            if text or user or date_v:
                notes_list.append({
                    "date": date_v,
                    "user": user,
                    "author": user,
                    "note": text,
                    "text": text,
                })
        if notes_list and not notes_text:
            joined = "; ".join(n.get("text", "") for n in notes_list if n.get("text"))
            notes_text = _normalize_optional(joined)

    # 6. Tarifa asignada por día / Noches
    night_rates: list[dict[str, Any]] = []
    if tbl_rates:
        hdrs = _headers(tbl_rates)
        i_rd = _col_idx(hdrs, "fecha")
        i_rn = _col_idx(hdrs, "tarifa")
        i_rp = _col_idx(hdrs, "precio")
        for tr in tbl_rates.find_all("tr")[1:]:
            r_cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not r_cells:
                continue
            date_v = _cell_text(r_cells, i_rd) or r_cells[0]
            if not date_v:
                continue
            price_txt = _cell_text(r_cells, i_rp) or (r_cells[2] if len(r_cells) > 2 else "")
            amount = _parse_decimal(price_txt or None)
            night_rates.append({
                "date": date_v,
                "rate_name": _cell_text(r_cells, i_rn) or (r_cells[1] if len(r_cells) > 1 else ""),
                "price": price_txt,
                "amount": amount,
                "currency": "USD",
            })

    # 7. Historial de cambios / Auditoría (7 columnas reales)
    change_history: list[dict[str, Any]] = []
    if tbl_history:
        for tr in tbl_history.find_all("tr")[1:]:
            tds = tr.find_all(["td", "th"])
            if not tds:
                continue
            h_cells = [td.get_text(" ", strip=True) for td in tds]
            if len(h_cells) < 4 or not h_cells[0]:
                continue
            # [0] Fecha/hora, [1] №, [2] Usuario, [3] Tipo, [4] Acción, [5] Cantidad, [6] Descripción
            has_full = len(h_cells) >= 7
            event_type = h_cells[3] if has_full else "change"
            amount = _parse_decimal_optional(h_cells[5]) if has_full else None
            description = h_cells[6] if has_full else h_cells[-1]
            action = h_cells[4] if has_full else h_cells[2]
            user = h_cells[2] if has_full else h_cells[1]
            item_id = h_cells[1] if has_full else ""
            change_history.append({
                "datetime": h_cells[0],
                "date": h_cells[0],
                "id": item_id,
                "user": user,
                "event_type": event_type or "change",
                "type": event_type or "change",
                "action": action,
                "amount": amount,
                "description": description,
                "details": description,
            })

    if stay_info.get("room_number") or stay_info.get("category_name"):
        stay_info["room_name"] = f"{stay_info.get('room_number', '')} {stay_info.get('category_name', '')}".strip()

    # notes normalization: prefer explicit note text if present, else None
    if notes_text is None and notes_list:
        joined = "; ".join(n.get("text", "") for n in notes_list if n.get("text"))
        notes_text = _normalize_optional(joined)
    notes_out = notes_list if notes_list else (_normalize_optional(notes_text) if notes_text else [])

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
        "notes": notes_out,
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
        """Descarga y parsea completamente el folio de una reserva con reintentos."""
        client = await self._ensure_client()
        url = self.urls.reservation_detail_url(str(reservation_id))
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return parse_folio_complete(resp.text, str(reservation_id))
            except (httpx.RemoteProtocolError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < 2:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning(
                        "Folio deep fetch retry",
                        reservation_id=str(reservation_id),
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        if last_exc:
            raise last_exc
        raise RuntimeError("Folio fetch failed unexpectedly")
