"""
Constantes y selectores para scraping de OtelMS.
Centraliza URLs, selectores CSS/XPath, timeouts y códigos de estado.
"""
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class OtelMSSelectors:
    """Selectores CSS para elementos de OtelMS."""

    # Login
    LOGIN_FORM: Final[str] = "form[action*='DoLogIn']"
    LOGIN_USERNAME_INPUT: Final[str] = "input[name='login']"
    LOGIN_PASSWORD_INPUT: Final[str] = "input[name='password']"
    LOGIN_SUBMIT_BUTTON: Final[str] = "button[type='submit'], input[type='submit']"
    LOGIN_ERROR_MESSAGE: Final[str] = ".alert-danger, .error-message, .login-error"

    # Calendar / Grid
    CALENDAR_TABLE: Final[str] = "table.calendar_table"
    CALENDAR_ROOM_ROW: Final[str] = "tr.room_row"
    CALENDAR_CELL: Final[str] = "td.calendar_cell"
    CALENDAR_CELL_OCCUPIED: Final[str] = "td.calendar_cell.occupied"
    CALENDAR_CELL_AVAILABLE: Final[str] = "td.calendar_cell.available"
    CALENDAR_CELL_LOCKED: Final[str] = "td.calendar_cell.locked"
    CALENDAR_ITEM: Final[str] = "div.calendar_item[resid]"
    CALENDAR_TOOLTIP: Final[str] = "div.tooltip_content"
    CALENDAR_DATE_HEADER: Final[str] = "th.calendar_date"
    CALENDAR_CATEGORY_ROW: Final[str] = "tr.category_row"

    # Reservation Detail (Folio)
    DETAIL_PANEL: Final[str] = "div.panel"
    DETAIL_PANEL_HEADING: Final[str] = "div.panel-heading"
    DETAIL_PANEL_BODY: Final[str] = "div.panel-body"
    DETAIL_RESERVATION_NUMBER: Final[str] = "h2.nameofgroup"
    DETAIL_BALANCE: Final[str] = "div.balans"
    DETAIL_EDIT_BUTTON: Final[str] = "#edit_reservation"
    DETAIL_MODAL: Final[str] = "div.modal-dialog:has(#modalform)"
    DETAIL_MODAL_FORM: Final[str] = "#modalform"
    DETAIL_GUEST_LINK: Final[str] = "a[href*='guestfolio']"

    # Guest Detail
    GUEST_PANEL: Final[str] = "div.panel:has(div.panel-heading:contains('Tarjeta de huésped'))"
    GUEST_HEADER_TIME: Final[str] = "span.header-time"
    GUEST_FOLIO_LINK: Final[str] = "a[href*='foliogroup']"
    GUEST_FIELDS_CONTAINER: Final[str] = "div.folio1, div.panel-body"
    GUEST_FIELD_LABEL: Final[str] = "div.col-md-2 b"
    GUEST_FIELD_VALUE: Final[str] = "div.col-md-2"

    # Reservation Modal (click en celda)
    MODAL_CONTENT: Final[str] = "div.modal-content"
    MODAL_HEADER: Final[str] = "div.modal-header"
    MODAL_TITLE: Final[str] = "h2.nameofgroup"
    MODAL_BODY: Final[str] = "div.modal-body"
    MODAL_FIELDS: Final[str] = "span.incolor"
    MODAL_FIELD_VALUE: Final[str] = "div.text-right"
    MODAL_GUEST_LIST: Final[str] = "span.incolor:contains('Lista de huéspedes') + div.text-right"
    MODAL_BALANCE: Final[str] = "div.balans"
    MODAL_CLOSE: Final[str] = "button.close, .modal-header .close"

    # Accommodation Modal (Editar reserva)
    ACCOMMODATION_MODAL: Final[str] = "div.modal-dialog:has(#modalform)"
    ACCOMMODATION_FORM: Final[str] = "#modalform"
    ACCOMMODATION_FIELDS: Final[str] = "div.form-group"
    ACCOMMODATION_LABEL: Final[str] = "label.control-label"
    ACCOMMODATION_INPUT: Final[str] = "input.form-control, select.form-control"

    # Pagination / Navigation
    DATE_NAV_PREV: Final[str] = "a.prev_date, button.prev_date"
    DATE_NAV_NEXT: Final[str] = "a.next_date, button.next_date"
    DATE_NAV_CURRENT: Final[str] = "span.current_date, input.current_date"


@dataclass(frozen=True)
class OtelMSUrls:
    """Constructores de URLs para OtelMS."""

    base_domain: str
    hotel_id: str

    @property
    def base_url(self) -> str:
        return f"https://{self.hotel_id}.{self.base_domain}"

    @property
    def login_url(self) -> str:
        return f"{self.base_url}/login/DoLogIn/"

    def calendar_url(self, date: str | None = None) -> str:
        url = f"{self.base_url}/reservation_c2/calendar"
        if date:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}date={date}"
        return url

    def reservation_detail_url(self, reservation_id: str) -> str:
        return f"{self.base_url}/reservation_c2/folio/{reservation_id}/1"

    def reservation_edit_url(self, reservation_id: str) -> str:
        return f"{self.base_url}/reservation_c2/edit/{reservation_id}"

    def guest_detail_url(self, guest_id: str) -> str:
        return f"{self.base_url}/reservation_c2/guestfolio/{guest_id}"


@dataclass(frozen=True)
class ReservationStatus:
    """Estados de reserva en OtelMS."""
    RESERVATION: Final[int] = 1      # Reservación
    CHECK_IN: Final[int] = 2         # Check-in / Alojamiento
    CHECK_OUT: Final[int] = 3        # Check-out / Salida
    CANCELLED: Final[int] = 4        # Cancelada (si existe)
    NO_SHOW: Final[int] = 5          # No show (si existe)

    @classmethod
    def from_text(cls, text: str) -> int | None:
        text_lower = text.lower().strip()
        if "reserva" in text_lower or "reservación" in text_lower:
            return cls.RESERVATION
        if "llegada" in text_lower or "alojamiento" in text_lower or "check.?in" in text_lower:
            return cls.CHECK_IN
        if "salida" in text_lower or "check.?out" in text_lower:
            return cls.CHECK_OUT
        if "cancel" in text_lower:
            return cls.CANCELLED
        if "no.?show" in text_lower:
            return cls.NO_SHOW
        # Intentar extraer número
        import re
        match = re.search(r"\b([1-5])\b", text)
        if match:
            return int(match.group(1))
        return None

    @classmethod
    def to_label(cls, status: int) -> str:
        labels = {
            cls.RESERVATION: "Reservación",
            cls.CHECK_IN: "Alojamiento",
            cls.CHECK_OUT: "Salida",
            cls.CANCELLED: "Cancelada",
            cls.NO_SHOW: "No Show",
        }
        return labels.get(status, f"Desconocido ({status})")


@dataclass(frozen=True)
class CellStatus:
    """Estados de celda en el calendario."""
    OCCUPIED: Final[str] = "occupied"
    AVAILABLE: Final[str] = "available"
    LOCKED: Final[str] = "locked"
    MAINTENANCE: Final[str] = "maintenance"
    OUT_OF_ORDER: Final[str] = "out_of_order"

    @classmethod
    def from_class(cls, css_class: str) -> str:
        css_lower = css_class.lower()
        if "occupied" in css_lower:
            return cls.OCCUPIED
        if "available" in css_lower:
            return cls.AVAILABLE
        if "locked" in css_lower:
            return cls.LOCKED
        if "maintenance" in css_lower:
            return cls.MAINTENANCE
        if "order" in css_lower:
            return cls.OUT_OF_ORDER
        return cls.AVAILABLE


# Timeouts por defecto (ms)
class Timeouts:
    PAGE_LOAD: Final[int] = 60000
    NAVIGATION: Final[int] = 45000
    SELECTOR: Final[int] = 20000
    MODAL_OPEN: Final[int] = 10000
    MODAL_CLOSE: Final[int] = 5000
    NETWORK_IDLE: Final[int] = 5000
    SCRIPT_EXECUTION: Final[int] = 30000


# Regex patterns para extracción
class Patterns:
    RESERVATION_ID: Final[str] = r"resid[\"']?\s*[:=]\s*[\"']?(\d+)"
    GUEST_ID_FROM_URL: Final[str] = r"/guestfolio/(\d+)"
    GUEST_ID_FROM_HEADER: Final[str] = r"ID:\s*(\d+)"
    DATE_ISO: Final[str] = r"\d{4}-\d{2}-\d{2}"
    DATETIME_ISO: Final[str] = r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}"
    CURRENCY: Final[str] = r"[\$\€\£]?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)"
    PHONE: Final[str] = r"[\+]?[\d\s\-\(\)]{7,}"
    EMAIL: Final[str] = r"[\w\.-]+@[\w\.-]+\.\w+"