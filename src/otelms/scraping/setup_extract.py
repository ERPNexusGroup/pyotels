"""
Extractor HTTP para páginas maestras de configuración y estado de OtelMS:
- Datos de la empresa: /setup_property_c2/property_information
- Servicios del hotel: /setup_property_c2/property_description
- Métodos de pago: /setup_payment_types_c2/type_list/1
- Fuentes de venta: /setup_dealers_c2/dealers_list/1
- Categorías oficiales: /setup_categories_c2/categories_list
- Habitaciones físicas: /setup_rooms_c2/room_list/1
- Estado operativo (Check-in / Check-out / In-House): /reservation_c2/status
- Tarifas generales por canal: /reservation_c2/price_calendar
"""
import asyncio
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import settings
from otelms.scraping.auth import get_authenticated_http_session
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class SetupExtractor:
    """Extrae datos maestros de configuración y estado operativo desde OtelMS."""

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

    async def __aenter__(self) -> "SetupExtractor":
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

    async def _get_with_retry(self, url: str, attempts: int = 4) -> httpx.Response:
        """GET con reintentos y backoff ante desconexiones remotas/timeouts/rate limits."""
        client = await self._ensure_client()
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await client.get(url)
                if resp.status_code == 429 and attempt < attempts - 1:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else 1.5 * (2 ** attempt)
                    except Exception:
                        delay = 1.5 * (2 ** attempt)
                    logger.warning("Setup GET rate limited, retrying", url=url, attempt=attempt + 1, delay_s=delay)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                body_lower = (resp.text or "").lower()
                if "do_single_login" in body_lower or "single_login" in str(resp.url).lower():
                    raise httpx.HTTPStatusError("Session expired", request=resp.request, response=resp)
                return resp
            except (httpx.RemoteProtocolError, httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = isinstance(exc, (httpx.RemoteProtocolError, httpx.TimeoutException, httpx.TransportError)) or status in {429, 500, 502, 503, 504}
                if retryable and attempt < attempts - 1:
                    delay = 0.75 * (2 ** attempt)
                    logger.warning("Setup GET retry", url=url, attempt=attempt + 1, error=str(exc), status=status)
                    await asyncio.sleep(delay)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("Setup GET failed unexpectedly")

    # ============================================================
    # 1. DATOS DE LA EMPRESA / HOTEL
    # ============================================================
    async def extract_property_information(self) -> dict[str, Any]:
        """Extrae datos generales de la empresa / propiedad."""
        resp = await self._get_with_retry(self.urls.property_information_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        fields: dict[str, Any] = {}
        for inp in soup.find_all(["input", "textarea", "select"]):
            name = inp.get("name")
            if not name or name.startswith("_"):
                continue
            val = inp.get("value")
            if not val and inp.name == "textarea":
                val = inp.get_text(strip=True)
            if inp.name == "select":
                sel = inp.find("option", selected=True)
                val = sel.get_text(strip=True) if sel else val
            fields[name] = val.strip() if isinstance(val, str) else val

        return {
            "id": fields.get("id") or self.hotel_id,
            "name": fields.get("property_name"),
            "legal_name": fields.get("property_name_lat") or fields.get("id_partner"),
            "property_type": fields.get("property_type"),
            "street": fields.get("street"),
            "additional_info": fields.get("additional_information"),
            "city": fields.get("city"),
            "state": fields.get("state"),
            "post_code": fields.get("post_code"),
            "country": fields.get("country"),
            "gps_coordinates": fields.get("gps_coordinates"),
            "reception_phone": fields.get("reception_phone"),
            "email": fields.get("email"),
            "web_address": fields.get("web_address"),
            "star_rating": int(fields.get("star_rating", 0)) if str(fields.get("star_rating", "")).isdigit() else None,
            "check_in_time": fields.get("check_in_time"),
            "check_out_time": fields.get("check_out_time"),
            "timezone": fields.get("timezone"),
        }

    # ============================================================
    # 2. SERVICIOS Y AMENIDADES DEL HOTEL
    # ============================================================
    async def extract_property_description(self) -> dict[str, Any]:
        """Extrae la descripción y catálogo de servicios / amenidades del hotel."""
        resp = await self._get_with_retry(self.urls.property_description_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        active_amenities: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cb in soup.find_all("input", type="checkbox"):
            if not cb.has_attr("checked"):
                continue
            # Filtrar plantillas ocultas/clonadas
            classes = " ".join(cb.get("class") or [])
            parent_classes = " ".join((cb.parent.get("class") or []) if cb.parent else [])
            container = cb.find_parent(class_=re.compile(r"template|hidden|clone|sample", re.I))
            style = " ".join([str(cb.get("style") or ""), str((cb.parent.get("style") if cb.parent else "") or "")]).lower()
            if container or "template" in classes.lower() or "template" in parent_classes.lower():
                continue
            if "display:none" in style or "visibility:hidden" in style:
                continue

            label = cb.find_parent("label") or soup.find("label", attrs={"for": cb.get("id")})
            if not label:
                group = cb.find_parent(class_="form-group")
                if group:
                    label = group.find("label")
            label_text = label.get_text(" ", strip=True) if label else ""
            if not label_text or "{amenity_id}" in label_text or "amenity_types" in label_text:
                continue
            key = label_text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            cb_id = str(cb.get("id") or "").strip()
            raw_name = str(cb.get("name") or "").strip()
            clean_name = label_text if (not raw_name or "{amenity_id}" in raw_name) else raw_name
            active_amenities.append({
                "id": cb_id or None,
                "name": clean_name,
                "label": label_text,
                "is_active": True,
            })

        desc_ta = soup.find("textarea", attrs={"name": re.compile(r"desc", re.I)})
        description_text = desc_ta.get_text(strip=True) if desc_ta else ""

        return {
            "description": description_text,
            "active_services": active_amenities,
        }

    # ============================================================
    # 3. MÉTODOS DE PAGO
    # ============================================================
    async def extract_payment_types(self) -> list[dict[str, Any]]:
        """Extrae el catálogo maestro de métodos de pago configurados."""
        resp = await self._get_with_retry(self.urls.payment_types_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        payment_types: list[dict[str, Any]] = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) >= 3:
                num = tds[0].get_text(strip=True)
                name = tds[1].get_text(strip=True)
                type_desc = tds[2].get_text(strip=True)

                edit_link = tr.find("a", href=True)
                item_id = ""
                if edit_link:
                    m = re.search(r"/(\d+)$", edit_link.get("href", ""))
                    if m:
                        item_id = m.group(1)

                payment_types.append({
                    "id": item_id or num,
                    "name": name,
                    "type": type_desc,
                    "is_active": True,
                })

        return payment_types

    # ============================================================
    # 4. FUENTES DE VENTA / CANALES (DEALERS / OTAs)
    # ============================================================
    async def extract_dealers(self) -> list[dict[str, Any]]:
        """Extrae el catálogo maestro de fuentes de venta y canales (OTAs)."""
        resp = await self._get_with_retry(self.urls.dealers_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        dealers: list[dict[str, Any]] = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) >= 6:
                num = tds[0].get_text(strip=True)
                name = tds[1].get_text(strip=True)
                address = tds[2].get_text(strip=True)
                phone = tds[3].get_text(strip=True)

                edit_link = tr.find("a", href=True)
                dealer_id = ""
                if edit_link:
                    m = re.search(r"/(\d+)$", edit_link.get("href", ""))
                    if m:
                        dealer_id = m.group(1)

                dealers.append({
                    "id": dealer_id or num,
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "is_active": True,
                })

        return dealers

    # ============================================================
    # 5. CATEGORÍAS Y HABITACIONES MAESTRAS
    # ============================================================
    async def extract_categories(self) -> list[dict[str, Any]]:
        """Extrae el catálogo maestro de categorías de habitación."""
        resp = await self._get_with_retry(self.urls.categories_setup_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        categories: list[dict[str, Any]] = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) >= 6:
                cat_id = tds[1].get_text(strip=True)
                full_name = tds[3].get_text(strip=True)
                short_name = tds[4].get_text(strip=True)
                sort_order = tds[5].get_text(strip=True)

                categories.append({
                    "id": cat_id,
                    "name": full_name,
                    "short_name": short_name,
                    "sort_order": int(sort_order) if sort_order.isdigit() else 0,
                    "hotel_id": self.hotel_id,
                })

        return categories

    async def extract_rooms(self) -> list[dict[str, Any]]:
        """Extrae el catálogo maestro de habitaciones físicas y su categoría asignada."""
        resp = await self._get_with_retry(self.urls.rooms_setup_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        # Detectar columnas por cabecera cuando sea posible
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        def idx_of(*names: str) -> int | None:
            for i, h in enumerate(headers):
                for n in names:
                    if n in h:
                        return i
            return None
        i_name = idx_of("habitación", "habitacion", "nombre", "número", "numero")
        i_cat = idx_of("categoría", "categoria")
        i_floor = idx_of("piso", "planta", "floor")
        i_occ = idx_of("ocupación", "ocupacion", "capacidad", "max")

        rooms: list[dict[str, Any]] = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            room_name = tds[i_name].get_text(strip=True) if i_name is not None and i_name < len(tds) else tds[1].get_text(strip=True)
            category_name = tds[i_cat].get_text(strip=True) if i_cat is not None and i_cat < len(tds) else (tds[2].get_text(strip=True) if len(tds) > 2 else "")
            floor = tds[i_floor].get_text(strip=True) if i_floor is not None and i_floor < len(tds) else (tds[5].get_text(strip=True) if len(tds) > 5 else "")
            occ_val = tds[i_occ].get_text(strip=True) if i_occ is not None and i_occ < len(tds) else ""
            max_occupancy = int(occ_val) if occ_val.isdigit() else None

            edit_link = tr.find("a", href=True)
            room_id = ""
            if edit_link:
                m = re.search(r"/(\d+)$", edit_link.get("href", ""))
                if m:
                    room_id = m.group(1)

            room_item: dict[str, Any] = {
                "id": room_id or room_name,
                "name": room_name,
                "category_name": category_name,
                "floor": floor or None,
                "hotel_id": self.hotel_id,
                "is_active": True,
            }
            if max_occupancy is not None:
                room_item["max_occupancy"] = max_occupancy
            rooms.append(room_item)

        return rooms

    # ============================================================
    # 6. ESTADO OPERATIVO (FRONT DESK: LLEGADAS, SALIDAS, ALOJADOS)
    # ============================================================
    async def extract_status(self) -> dict[str, Any]:
        """Extrae el estado operativo en vivo: llegadas pendientes, salidas y huéspedes alojados."""
        resp = await self._get_with_retry(self.urls.status_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        status_data: dict[str, Any] = {
            "arrivals_count": 0,
            "departures_count": 0,
            "in_house_count": 0,
            "arrivals": [],
            "departures": [],
            "in_house": [],
        }

        # Analizar contadores y tarjetas de status
        for card in soup.find_all(class_=lambda c: c and any(x in str(c).lower() for x in ["panel", "box", "widget", "desk"])):
            head = card.find(["h3", "h4", "h2", "span"])
            if not head:
                continue
            text = head.get_text(strip=True).lower()

            count_match = re.search(r"(\d+)", text)
            count = int(count_match.group(1)) if count_match else 0

            if "llegada" in text or "arrival" in text or "check in" in text:
                status_data["arrivals_count"] = count
            elif "salida" in text or "departure" in text or "check out" in text:
                status_data["departures_count"] = count
            elif "alojad" in text or "in house" in text or "hosped" in text:
                status_data["in_house_count"] = count

        from datetime import date
        today_str = date.today().isoformat()
        status_data["status_date"] = today_str
        status_data["arrivals_today"] = status_data["arrivals_count"]
        status_data["departures_today"] = status_data["departures_count"]
        status_data["inhouse_today"] = status_data["in_house_count"]

        return status_data

    # ============================================================
    # 7. TARIFAS Y PRECIOS POR CANAL DE VENTA (/price_calendar)
    # ============================================================
    async def extract_price_calendar(self, target_date: str | None = None) -> list[dict[str, Any]]:
        """Extrae la matriz de precios por canal de venta, categoría y fecha."""
        url = self.urls.price_calendar_url
        if target_date:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}date={target_date}"

        resp = await self._get_with_retry(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        rates_data: list[dict[str, Any]] = []
        for tr in soup.find_all("tr", class_="ui-selectable"):
            for td in tr.find_all("td", class_="calendar_td"):
                fulldate = td.get("fulldate")
                cat_id = td.get("category_id")
                rate_id = td.get("rate_id") or td.get("hms_rate_id")
                title = td.get("title") or ""
                price_text = td.get_text(strip=True)

                if fulldate and cat_id and price_text:
                    # Limpiar precio numérico
                    clean_price = price_text.replace("$", "").replace(",", ".").strip()
                    try:
                        price_val = float(clean_price)
                    except ValueError:
                        price_val = 0.0

                    # Título suele ser "Directa, 2026-11-09" o nombre de canal
                    channel_name = title.split(",")[0].strip() if "," in title else title

                    rates_data.append({
                        "category_id": cat_id,
                        "rate_id": rate_id or "1",
                        "channel": channel_name or "Directa",
                        "date": fulldate,
                        "price": price_val,
                        "hotel_id": self.hotel_id,
                    })

        logger.info("Price calendar extracted", rates_count=len(rates_data), hotel_id=self.hotel_id)
        return rates_data

    # ============================================================
    # EXTRACTOR COMPLETO DE SETUP
    # ============================================================
    async def extract_all_setup(self) -> dict[str, Any]:
        """Extrae toda la configuración maestra del hotel en una sola pasada."""
        logger.info("Extracting all setup configuration", hotel_id=self.hotel_id)
        prop = await self.extract_property_information()
        desc = await self.extract_property_description()
        payments = await self.extract_payment_types()
        dealers = await self.extract_dealers()
        categories = await self.extract_categories()
        rooms = await self.extract_rooms()

        return {
            "hotel": prop,
            "services_catalog": desc,
            "payment_methods": payments,
            "dealers": dealers,
            "categories": categories,
            "rooms": rooms,
        }

    # Alias convenientes
    fetch_status = extract_status
    fetch_price_calendar = extract_price_calendar
