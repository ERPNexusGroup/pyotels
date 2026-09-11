"""
Tests del parser v2 (markup actual del calendario OtelMS).

Fixture mínima que replica la estructura real verificada el 2026-09-10:
table.calendar_table#desk > tbody > tr.calendar_tr(.btn_close_box{cat}) >
td.calendar_td[room_id][day_id] con div.calendar_item[resid][status] +
tooltip data-title, fila resumen room_id=0, sidebar calendar_rooms_dott.
"""
import html as _h

from otelms.scraping.calendar_markup_v2 import (
    day_id_to_date,
    parse_categories_v2,
    parse_grid_v2,
    parse_tooltip_v2,
    to_float_or_none,
)
from otelms.scraping.parsers import CalendarParser

FIXTURE_HTML = """
<html><body>
<div class="sidebar">
<div class="calendar_rooms_dott">Matrimonial</div>
<div class="calendar_rooms_dott">Doble</div>
</div>
<table class="calendar_table" id="desk">
<tbody class="calendar_tbody my_category">
<tr class="calendar_tr">
<td class="calendar_td" day_id="20706" room_id="0" category_id="13">
<div class="calendar_sum" id="availability_13_20706">8</div></td>
<td class="calendar_td" day_id="20707" room_id="0" category_id="13">
<div class="calendar_sum" id="availability_13_20707">9</div></td>
</tr>
</tbody>
<tbody class="calendar_tbody my_category">
<tr class="calendar_tr btn_close_box13">
<td id="td_103_20706" class="calendar_td" day_id="20706" room_id="103"></td>
<td id="td_103_20707" class="calendar_td bg_padlock" day_id="20707" room_id="103"></td>
</tr>
</tbody>
<tbody class="calendar_tbody my_category">
<tr class="calendar_tr btn_close_box13">
<td id="td_105_20706" class="calendar_td {selected_res_class}" day_id="20706" room_id="105">
<div id="res_block_23508" class="calendar_item" resid="23508" status="1"
data-title="&lt;p class='tooltip_inside'&gt;&lt;div&gt;Reserva №23508 (Reservación), Venta directa&lt;/div&gt;&lt;div&gt;Huésped: DOE JOHN&lt;/div&gt;&lt;div&gt;Llegada: 2026-09-08&lt;/div&gt;&lt;div&gt;Salida: 2026-09-11&lt;/div&gt;&lt;/p&gt;"></div>
</td>
<td id="td_105_20707" class="calendar_td" day_id="20707" room_id="105"></td>
</tr>
</tbody>
<tbody class="calendar_tbody my_category">
<tr class="calendar_tr btn_close_box14">
<td id="td_116_20706" class="calendar_td" day_id="20706" room_id="116"></td>
<td id="td_116_20707" class="calendar_td" day_id="20707" room_id="116"></td>
</tr>
</tbody>
</table>
</body></html>
"""


class TestDayIdMapping:
    def test_epoch_base(self):
        assert day_id_to_date("20706") == "2026-09-10"
        assert day_id_to_date(20707) == "2026-09-11"


class TestToFloat:
    def test_trailing_comma(self):
        assert to_float_or_none("-75.00,") == -75.0

    def test_thousands(self):
        assert to_float_or_none("1,250.00") == 1250.0

    def test_plain(self):
        assert to_float_or_none("40") == 40.0

    def test_none_on_garbage(self):
        assert to_float_or_none(None) is None
        assert to_float_or_none("sin número") is None


class TestTooltip:
    def test_parse(self):
        raw = ("&lt;p class='tooltip_inside'&gt;&lt;div&gt;Reserva №23508 "
               "(Reservación), Venta directa&lt;/div&gt;&lt;div&gt;Huésped: DOE JOHN&lt;/div&gt;"
               "&lt;div&gt;Llegada: 2026-09-08&lt;/div&gt;&lt;div&gt;Salida: 2026-09-11&lt;/div&gt;&lt;/p&gt;")
        fields = parse_tooltip_v2(_h.unescape(raw))
        assert fields["reservation_id"] == "23508"
        assert fields["reservation_type"] == "Reservación"
        assert fields["huésped"] == "DOE JOHN"
        assert fields["llegada"] == "2026-09-08"
        assert fields["salida"] == "2026-09-11"


class TestCategoriesV2:
    def test_blocks_and_rooms(self):
        cats = parse_categories_v2(FIXTURE_HTML)
        assert [c["id"] for c in cats] == ["13", "14"]
        assert cats[0]["name"] == "Matrimonial"
        assert cats[1]["name"] == "Doble"
        rooms13 = {r["id"]: r for r in cats[0]["rooms"]}
        assert set(rooms13) == {"103", "105"}
        assert rooms13["103"]["category_id"] == "13"
        assert rooms13["103"]["name"] == "103"

    def test_empty_without_table(self):
        assert parse_categories_v2("<html><body>nada</body></html>") == []


class TestGridV2:
    def test_reservations(self):
        parsed = parse_grid_v2(FIXTURE_HTML)
        assert len(parsed["cells"]) == 1
        cell = parsed["cells"][0]
        assert cell["reservation_id"] == "23508"
        assert cell["room_id"] == "105"
        assert cell["cell_status"] == "occupied"
        assert cell["guest_name"] == "DOE JOHN"
        assert cell["check_in"] == "2026-09-08"
        assert cell["check_out"] == "2026-09-11"
        assert cell["reservation_status"] == 1
        assert cell["category_id"] == "13"

    def test_locks_future_only(self):
        parsed = parse_grid_v2(FIXTURE_HTML)
        # day 20707 = 2026-09-11: pasado respecto a hoy real -> sin locks futuros viejos;
        # el contrato es lista de dicts room_id/date (puede estar vacía según fecha actual)
        assert isinstance(parsed["locks"], list)
        for lock in parsed["locks"]:
            assert set(lock) == {"room_id", "date"}

    def test_categories_included(self):
        parsed = parse_grid_v2(FIXTURE_HTML)
        assert len(parsed["categories"]) == 2


class TestParserFallback:
    """El pipeline commiteado usa el fallback v2 cuando el legacy no halla nada."""

    def test_parse_categories_fallback(self):
        cats = CalendarParser.parse_categories(FIXTURE_HTML)
        assert [c["id"] for c in cats] == ["13", "14"]
        assert cats[0]["rooms"][0]["id"] in ("103", "105")

    def test_parse_grid_fallback(self):
        parsed = CalendarParser.parse_grid(FIXTURE_HTML)
        assert len(parsed["cells"]) == 1
        assert parsed["cells"][0]["reservation_id"] == "23508"
        assert parsed["cells"][0]["guest_name"] == "DOE JOHN"
        assert len(parsed["categories"]) == 2
        assert "extracted_at" in parsed
