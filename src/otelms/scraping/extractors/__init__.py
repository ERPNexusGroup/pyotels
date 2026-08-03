"""
Extractors para páginas de OtelMS.
Cada extractor maneja un tipo de página específico.
"""
import asyncio
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from otelms.config.constants import CellStatus, OtelMSSelectors, OtelMSUrls, ReservationStatus
from otelms.scraping.exceptions import ExtractionError, NavigationError
from otelms.scraping.retry import navigation_retry, with_retry
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CalendarCellData:
    """Datos de una celda del calendario."""
    room_id: str
    room_name: str
    category_id: str
    category_name: str
    date: str
    day_id: str
    cell_status: str  # occupied, available, locked
    reservation_id: str | None = None
    reservation_number: str | None = None
    guest_name: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    created_at: str | None = None
    guest_count: int | None = None
    balance: float | None = None
    phone: str | None = None
    email: str | None = None
    user: str | None = None
    comments: str | None = None
    reservation_status: int | None = None


@dataclass
class CategoryData:
    """Datos de categoría con habitaciones."""
    id: str
    name: str
    rooms: list[dict]


class CalendarExtractor:
    """Extractor para la página de calendario/grid."""

    def __init__(self, page: Page, urls: OtelMSUrls):
        self.page = page
        self.urls = urls
        self.selectors = OtelMSSelectors()

    async def navigate(self, date: str | None = None) -> None:
        """Navega al calendario."""
        url = self.urls.calendar_url(date)
        logger.debug("Navigating to calendar", url=url)

        await with_retry(
            self._goto_and_wait,
            url,
            retry_policy=navigation_retry,
        )

    async def _goto_and_wait(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Verificar login
        if "login" in self.page.url.lower():
            raise NavigationError("Redirected to login", url=url)

        # Esperar tabla de calendario
        try:
            await self.page.wait_for_selector(
                self.selectors.CALENDAR_TABLE,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            raise NavigationError("Calendar table not loaded", url=url) from None

        # Pequeña espera para renderizado dinámico
        await asyncio.sleep(0.5)

    async def extract_categories(self) -> list[CategoryData]:
        """Extrae categorías y habitaciones del calendario."""
        logger.debug("Extracting categories")

        html = await self.page.content()
        soup = BeautifulSoup(html, "lxml")

        categories = []
        table = soup.find("table", class_="calendar_table")
        if not table:
            raise ExtractionError("calendar_table not found", "table", html[:500])

        # Las categorías están en filas con class="category_row"
        for cat_row in table.find_all("tr", class_="category_row"):
            raw_cat_id = cat_row.get("data-category-id")
            cat_id = str(raw_cat_id) if raw_cat_id else str(cat_row.get("id", "")).replace("cat_", "")
            cat_name_elem = cat_row.find("td", class_="category_name") or cat_row.find("th", class_="category_name")
            cat_name = cat_name_elem.get_text(strip=True) if cat_name_elem else f"Category {cat_id}"

            rooms = []
            # Habitaciones están en filas siguientes con data-category-id
            for room_row in cat_row.find_next_siblings("tr", class_="room_row"):
                if room_row.get("data-category-id") != cat_id:
                    break
                raw_room_id = room_row.get("data-room-id")
                room_id = str(raw_room_id) if raw_room_id else str(room_row.get("id", "")).replace("room_", "")
                room_name_elem = room_row.find("td", class_="room_name") or room_row.find("th", class_="room_name")
                room_name = room_name_elem.get_text(strip=True) if room_name_elem else f"Room {room_id}"

                rooms.append({
                    "id": room_id,
                    "name": room_name,
                    "category_id": cat_id,
                })

            categories.append(CategoryData(
                id=cat_id,
                name=cat_name,
                rooms=rooms,
            ))

        logger.info("Categories extracted", count=len(categories))
        return categories

    async def extract_calendar_grid(self, date: str | None = None) -> list[CalendarCellData]:
        """Extrae toda la grilla de reservas del calendario."""
        logger.debug("Extracting calendar grid")

        # Primero extraer categorías para mapear room_id -> category
        categories = await self.extract_categories()
        room_to_category = {}
        for cat in categories:
            for room in cat.rooms:
                room_to_category[room["id"]] = {"id": cat.id, "name": cat.name}

        html = await self.page.content()
        soup = BeautifulSoup(html, "lxml")

        table = soup.find("table", class_="calendar_table")
        if not table:
            raise ExtractionError("calendar_table not found", "table", html[:500])

        cells_data = []
        day_id_to_date = self._extract_date_mapping(soup)

        # Iterar filas de habitaciones
        for room_row in table.find_all("tr", class_="room_row"):
            raw_room_id = room_row.get("data-room-id")
            room_id = str(raw_room_id) if raw_room_id else str(room_row.get("id", "")).replace("room_", "")
            room_name_elem = room_row.find("td", class_="room_name") or room_row.find("th", class_="room_name")
            room_name = room_name_elem.get_text(strip=True) if room_name_elem else room_id

            cat_info = room_to_category.get(room_id, {"id": "", "name": ""})

            # Iterar celdas de la fila
            for cell in room_row.find_all("td", class_="calendar_cell"):
                raw_day_id = cell.get("data-day-id")
                day_id = str(raw_day_id) if raw_day_id else str(cell.get("id", "")).replace("cell_", "")
                cell_date = day_id_to_date.get(day_id, date or "")
                cell_class = cell.get("class")
                cell_status = CellStatus.from_class(" ".join(str(c) for c in (cell_class or [])))

                cell_data = CalendarCellData(
                    room_id=room_id,
                    room_name=room_name,
                    category_id=cat_info["id"],
                    category_name=cat_info["name"],
                    date=cell_date,
                    day_id=day_id,
                    cell_status=cell_status,
                )

                # Si está ocupada, extraer datos de la reserva
                if cell_status == CellStatus.OCCUPIED:
                    item = cell.find("div", class_="calendar_item")
                    if item:
                        resid = item.get("resid")
                        if resid:
                            cell_data.reservation_id = str(resid)
                            # Extraer tooltip si existe
                            tooltip = item.find("div", class_="tooltip_content")
                            if tooltip:
                                self._parse_tooltip(tooltip, cell_data)  # type: ignore[arg-type]  # bs4 Tag vs BeautifulSoup, ambos tienen find/find_all

                cells_data.append(cell_data)

        logger.info("Calendar grid extracted", cells=len(cells_data), occupied=sum(1 for c in cells_data if c.cell_status == "occupied"))
        return cells_data

    def _extract_date_mapping(self, soup: BeautifulSoup) -> dict[str, str]:
        """Extrae mapeo day_id -> date del header del calendario."""
        mapping = {}
        header_row = soup.find("tr", class_="calendar_header") or soup.find("thead")
        if header_row:
            for th in header_row.find_all("th", class_="calendar_date"):
                day_id = th.get("data-day-id")
                date_text = str(th.get("data-date") or th.get_text(strip=True))
                if day_id and date_text:
                    mapping[str(day_id)] = date_text
        return mapping

    def _parse_tooltip(self, tooltip: BeautifulSoup, cell_data: CalendarCellData) -> None:
        """Parsea tooltip de reserva.

        NOTA: Duplicado en parsers/__init__.py con firma distinta (cell_data: dict).
        Futuro: unificar en utils/parse_tooltip.py para DRY.
        """
        text = tooltip.get_text(" ", strip=True)

        # Regex patterns
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
                if field in ["guest_count"]:
                    value = int(value) if value.isdigit() else None
                elif field == "balance":
                    value = float(value.replace(",", "")) if value else None
                setattr(cell_data, field, value)

        # Status de reserva (1, 2, 3)
        status_match = re.search(r"(?:Reserva|Salida|Alojamiento).*?(\d)", text)
        if status_match:
            cell_data.reservation_status = ReservationStatus.from_text(status_match.group(0))


class ReservationDetailExtractor:
    """Extractor para página de detalle de reserva (folio)."""

    def __init__(self, page: Page, urls: OtelMSUrls):
        self.page = page
        self.urls = urls
        self.selectors = OtelMSSelectors()

    async def navigate(self, reservation_id: str) -> None:
        """Navega al detalle de reserva."""
        url = self.urls.reservation_detail_url(reservation_id)
        logger.debug("Navigating to reservation detail", url=url, reservation_id=reservation_id)

        await with_retry(
            self._goto_and_wait,
            url,
            retry_policy=navigation_retry,
        )

    async def _goto_and_wait(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

        if "login" in self.page.url.lower():
            raise NavigationError("Session expired", url=url)

        try:
            await self.page.wait_for_selector(
                self.selectors.DETAIL_PANEL,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            logger.warning("Detail panel not found, continuing anyway")

    async def extract_basic_info(self) -> dict[str, Any]:
        """Extrae información básica del folio."""
        html = await self.page.content()
        soup = BeautifulSoup(html, "lxml")

        data: dict[str, Any] = {}

        # Número de reserva y status
        h2 = soup.find("h2", class_="nameofgroup")
        if h2:
            text = h2.get_text(strip=True)
            # Formato: "Reserva 12345" o "Alojamiento 12345"
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
            try:
                data["balance"] = float(balance_text.replace(",", ""))
            except ValueError:
                pass

        # Campos clave-valor
        fields_map = {}
        for label_tag in soup.find_all("span", class_="incolor"):
            key = label_tag.get_text(strip=True)
            parent = label_tag.find_parent("div")
            if not parent:
                continue
            value_div = parent.find_next_sibling("div", class_="text-right")
            if value_div:
                # Verificar si es imagen (source)
                img = value_div.find("img")
                if img and "dc_logo" in str(img.get("src", "")):
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

        for field_label, value in fields_map.items():
            field = field_mapping.get(field_label)
            if field:
                data[field] = value

        # Lista de huéspedes
        guest_label = soup.find("span", class_="incolor", string="Lista de huéspedes")  # type: ignore[call-overload]  # bs4 acepta string= en kwargs
        if guest_label:
            parent = guest_label.find_parent("div")
            if parent:
                guest_div = parent.find_next_sibling("div", class_="text-right")
                if guest_div:
                    data["guest_list"] = list(guest_div.stripped_strings)

        return data

    async def click_edit_button(self) -> bool:
        """Hace clic en botón Editar para abrir modal de alojamiento."""
        try:
            await self.page.wait_for_selector(
                self.selectors.DETAIL_EDIT_BUTTON,
                state="visible",
                timeout=10000,
            )
            await self.page.click(self.selectors.DETAIL_EDIT_BUTTON)

            # Esperar modal
            await self.page.wait_for_selector(
                self.selectors.DETAIL_MODAL,
                state="visible",
                timeout=10000,
            )
            await asyncio.sleep(0.5)
            return True
        except PlaywrightTimeoutError:
            logger.warning("Edit button or modal not found")
            return False

    async def extract_accommodation_modal(self) -> dict[str, Any]:
        """Extrae HTML del modal de edición de alojamiento."""
        modal = await self.page.query_selector(self.selectors.DETAIL_MODAL)
        if not modal:
            raise ExtractionError("Accommodation modal not found", "modal", "")

        html = await modal.evaluate("el => el.outerHTML")

        # Cerrar modal
        await self.page.keyboard.press("Escape")

        return {"html": html}

    async def close_modal_if_open(self) -> None:
        """Cierra modal si está abierto."""
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
        except Exception:
            pass


class GuestDetailExtractor:
    """Extractor para página de detalle de huésped."""

    def __init__(self, page: Page, urls: OtelMSUrls):
        self.page = page
        self.urls = urls
        self.selectors = OtelMSSelectors()

    async def navigate(self, guest_id: str) -> None:
        """Navega al detalle de huésped."""
        url = self.urls.guest_detail_url(guest_id)
        logger.debug("Navigating to guest detail", url=url, guest_id=guest_id)

        await with_retry(
            self._goto_and_wait,
            url,
            retry_policy=navigation_retry,
        )

    async def _goto_and_wait(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

        if "login" in self.page.url.lower():
            raise NavigationError("Session expired", url=url)

        try:
            await self.page.wait_for_selector(
                self.selectors.GUEST_PANEL,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            logger.warning("Guest panel not found, continuing anyway")

    async def extract(self) -> dict[str, Any]:
        """Extrae datos del huésped."""
        html = await self.page.content()
        soup = BeautifulSoup(html, "lxml")

        data = {}

        # ID del huésped desde header
        header = soup.find("span", class_="header-time")
        if header:
            text = header.get_text(" ", strip=True)
            match = re.search(r"ID:\s*(\d+)", text)
            if match:
                data["id"] = match.group(1)

        # Buscar panel "Tarjeta de huésped"
        panel = None
        for p in soup.find_all("div", class_="panel"):
            heading = p.find("div", class_="panel-heading")
            if heading and "Tarjeta de huésped" in heading.get_text():
                panel = p
                break

        if not panel:
            # Fallback: buscar por widget
            panel = soup.find("div", attrs={"data-widget": lambda x: bool(x and "wiget1" in str(x))})

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
                        elif getattr(curr, "name", None) == "br":
                            pass
                        else:
                            val += curr.get_text(" ", strip=True)
                        curr = curr.next_sibling

                    val = val.strip()
                    data[key] = val

        return data


class ModalExtractor:
    """Extractor para modales de reserva (click en celda del calendario)."""

    def __init__(self, page: Page):
        self.page = page
        self.selectors = OtelMSSelectors()

    async def open_modal(self, reservation_id: str) -> bool:
        """Abre modal haciendo clic en la reserva del calendario."""
        try:
            # Asegurar que estamos en el calendario
            if "calendar" not in self.page.url:
                raise NavigationError("Not on calendar page")

            # Buscar y clicar la reserva
            selector = f"div[resid='{reservation_id}']"
            await self.page.wait_for_selector(selector, state="visible", timeout=10000)
            await self.page.click(selector, force=True)

            # Esperar modal
            await self.page.wait_for_selector(
                self.selectors.MODAL_CONTENT,
                state="visible",
                timeout=10000,
            )
            await asyncio.sleep(0.5)
            return True
        except PlaywrightTimeoutError:
            logger.warning("Modal not found for reservation", reservation_id=reservation_id)
            return False

    async def extract_modal(self) -> dict[str, Any]:
        """Extrae HTML del modal abierto."""
        modal = await self.page.query_selector(self.selectors.MODAL_CONTENT)
        if not modal:
            raise ExtractionError("Modal content not found", "modal", "")

        html = await modal.inner_html()

        # Cerrar modal
        await self.page.keyboard.press("Escape")
        try:
            await self.page.wait_for_selector(
                self.selectors.MODAL_CONTENT,
                state="hidden",
                timeout=5000,
            )
        except PlaywrightTimeoutError:
            pass

        return {"html": html, "reservation_id": None}

    async def extract_all_modals(self, reservation_ids: list[str]) -> dict[str, str]:
        """Extrae modales para múltiples reservas."""
        results = {}
        for res_id in reservation_ids:
            try:
                if await self.open_modal(res_id):
                    data = await self.extract_modal()
                    results[res_id] = data["html"]
                    await asyncio.sleep(0.2)  # Rate limiting suave
            except Exception as e:
                logger.error("Error extracting modal", reservation_id=res_id, error=str(e))
        return results
