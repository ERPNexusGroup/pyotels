"""
Unit tests for parsers.
"""
import pytest
from datetime import datetime

from otelms.scraping.parsers import (
    CalendarParser,
    ReservationDetailParser,
    GuestDetailParser,
    ModalParser,
    normalize_float,
    normalize_decimal,
    normalize_date,
    normalize_datetime,
)


class TestNormalizers:
    """Tests for normalization functions."""

    def test_normalize_float_valid(self):
        assert normalize_float("123.45") == 123.45
        assert normalize_float("$1,234.56") == 1234.56
        assert normalize_float("€ 99,99") == 99.99
        assert normalize_float("-50.00") == -50.00

    def test_normalize_float_invalid(self):
        assert normalize_float("") is None
        assert normalize_float(None) is None
        assert normalize_float("abc") is None

    def test_normalize_decimal_valid(self):
        from decimal import Decimal
        assert normalize_decimal("123.45") == Decimal("123.45")
        assert normalize_decimal("$1,234.56") == Decimal("1234.56")

    def test_normalize_date_valid(self):
        assert normalize_date("2026-01-15") == "2026-01-15"
        assert normalize_date("15/01/2026") == "2026-01-15"
        assert normalize_date("15-01-2026") == "2026-01-15"
        assert normalize_date("2026/01/15") == "2026-01-15"
        assert normalize_date("15.01.2026") == "2026-01-15"

    def test_normalize_date_invalid(self):
        assert normalize_date("") is None
        assert normalize_date(None) is None
        assert normalize_date("invalid") is None

    def test_normalize_datetime_valid(self):
        assert normalize_datetime("2026-01-15 14:30:00") == "2026-01-15T14:30:00"
        assert normalize_datetime("2026-01-15T14:30:00") == "2026-01-15T14:30:00"

    def test_normalize_datetime_invalid(self):
        assert normalize_datetime("") is None
        assert normalize_datetime(None) is None


class TestCalendarParser:
    """Tests for CalendarParser."""

    def test_parse_categories_empty(self):
        html = "<table class='calendar_table'></table>"
        result = CalendarParser.parse_categories(html)
        assert result == []

    def test_parse_categories_with_data(self):
        html = """
        <table class="calendar_table">
            <tr class="category_row" data-category-id="cat_1">
                <td class="category_name">Standard</td>
            </tr>
            <tr class="room_row" data-category-id="cat_1" data-room-id="room_1">
                <td class="room_name">101</td>
            </tr>
            <tr class="room_row" data-category-id="cat_1" data-room-id="room_2">
                <td class="room_name">102</td>
            </tr>
        </table>
        """
        result = CalendarParser.parse_categories(html)
        assert len(result) == 1
        assert result[0]["id"] == "cat_1"
        assert result[0]["name"] == "Standard"
        assert len(result[0]["rooms"]) == 2
        assert result[0]["rooms"][0]["id"] == "room_1"
        assert result[0]["rooms"][0]["name"] == "101"

    def test_parse_grid_empty(self):
        html = "<table class='calendar_table'></table>"
        result = CalendarParser.parse_grid(html)
        assert result["cells"] == []
        assert result["categories"] == []


class TestReservationDetailParser:
    """Tests for ReservationDetailParser."""

    def test_parse_basic_info_empty(self):
        html = "<div class='panel'></div>"
        result = ReservationDetailParser.parse_basic_info(html)
        assert result == {}

    def test_parse_basic_info_with_data(self):
        html = """
        <div class="panel">
            <h2 class="nameofgroup">Reserva 12345</h2>
            <div class="balans">Saldo: $150.00</div>
            <span class="incolor">Huésped</span>
            <div class="text-right">Juan Pérez</div>
            <span class="incolor">Llegada</span>
            <div class="text-right">2026-01-15</div>
            <span class="incolor">Salida</span>
            <div class="text-right">2026-01-18</div>
        </div>
        """
        result = ReservationDetailParser.parse_basic_info(html)
        assert result["reservation_number"] == "12345"
        assert result["balance"] == 150.0
        assert result["guest_name"] == "Juan Pérez"
        assert result["check_in"] == "2026-01-15"
        assert result["check_out"] == "2026-01-18"


class TestGuestDetailParser:
    """Tests for GuestDetailParser."""

    def test_parse_empty(self):
        html = "<div class='panel'></div>"
        result = GuestDetailParser.parse(html)
        assert result == {}

    def test_parse_with_data(self):
        html = """
        <div class="panel">
            <div class="panel-heading">Tarjeta de huésped</div>
            <div class="panel-body">
                <div class="folio1">
                    <div class="col-md-2"><b>Nombre:</b> Juan</div>
                    <div class="col-md-2"><b>Apellido:</b> Pérez</div>
                    <div class="col-md-2"><b>Email:</b> juan@test.com</div>
                    <div class="col-md-2"><b>Teléfono:</b> +1234567890</div>
                </div>
            </div>
        </div>
        """
        result = GuestDetailParser.parse(html)
        assert result["first_name"] == "Juan"
        assert result["last_name"] == "Pérez"
        assert result["email"] == "juan@test.com"
        assert result["phone"] == "+1234567890"
        assert result["name"] == "Juan Pérez"


class TestModalParser:
    """Tests for ModalParser."""

    def test_parse_empty(self):
        html = "<div class='modal-content'></div>"
        result = ModalParser.parse(html)
        assert result == {}

    def test_parse_with_data(self):
        html = """
        <div class="modal-content">
            <h2 class="nameofgroup">Reserva 12345</h2>
            <div class="balans">Saldo: $200.00</div>
            <span class="incolor">Huésped</span>
            <div class="text-right">María García</div>
            <span class="incolor">Llegada</span>
            <div class="text-right">2026-02-01</div>
            <span class="incolor">Salida</span>
            <div class="text-right">2026-02-05</div>
        </div>
        """
        result = ModalParser.parse(html, reservation_id="12345")
        assert result["reservation_number"] == "12345"
        assert result["balance"] == 200.0
        assert result["guest_name"] == "María García"
        assert result["check_in"] == "2026-02-01"
        assert result["check_out"] == "2026-02-05"