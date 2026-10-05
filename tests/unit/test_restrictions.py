"""
Tests de restrictions (close/open dates) contra httpx.MockTransport.

No tocan el portal: el cliente HTTP se inyecta ya autenticado, así que solo se
verifica el contrato con /reservation_c2/save_restrict_close_open
(restrict_type 0=cierra, 1=abre) y el parseo de /reservation_c2/restrict_calendar.
"""
from urllib.parse import parse_qs

import httpx
import pytest

from otelms.scraping import restrictions

RESTRICT_CALENDAR_HTML = """
<html><body>
<form>
  <select name="categories[]">
    <option value="13">Matrimonial</option>
    <option value="15">Triple</option>
  </select>
</form>
</body></html>
"""


class _Recorder:
    """Captura las peticiones hechas al transport mock."""

    def __init__(self, status: int = 200, html: str = ""):
        self.calls: list[httpx.Request] = []
        self._status = status
        self._html = html

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self._status != 200:
            return httpx.Response(self._status, text="error")
        return httpx.Response(200, html=self._html)

    @property
    def last(self) -> httpx.Request:
        return self.calls[-1]

    def form(self) -> dict[str, list[str]]:
        # parse_qs y no httpx.QueryParams: este último colapsa las claves
        # repetidas (categories[]) y solo devolvería la última.
        return parse_qs(self.last.content.decode())


def _client(rec: _Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://desktop.otelms.com",
        transport=httpx.MockTransport(rec.handler),
    )


class TestCloseOpenDates:
    async def test_close_posts_restrict_type_zero(self):
        rec = _Recorder()
        async with _client(rec) as client:
            ok = await restrictions.close_dates(
                "18330", "2026-03-01", "2026-03-03",
                categories=["Matrimonial"], client=client,
            )
        assert ok is True
        assert rec.last.url.path == restrictions.RESTRICT_URL
        assert rec.form()["restrict_type"] == ["0"]
        assert rec.form()["date"] == ["2026-03-01 - 2026-03-03"]
        assert rec.form()["categories[]"] == ["13"]

    async def test_open_posts_restrict_type_one(self):
        rec = _Recorder()
        async with _client(rec) as client:
            ok = await restrictions.open_dates(
                "18330", "2026-03-01", "2026-03-03",
                categories=["Triple"], client=client,
            )
        assert ok is True
        assert rec.form()["restrict_type"] == ["1"]
        assert rec.form()["categories[]"] == ["15"]

    async def test_no_categories_targets_all(self):
        rec = _Recorder()
        async with _client(rec) as client:
            await restrictions.close_dates("18330", "2026-03-01", "2026-03-02", client=client)
        sent = rec.form()["categories[]"]
        assert set(sent) == set(restrictions.CATEGORY_IDS.values())
        assert len(sent) == 9

    async def test_ajax_header_is_sent(self):
        rec = _Recorder()
        async with _client(rec) as client:
            await restrictions.close_dates("18330", "2026-03-01", "2026-03-02", client=client)
        assert rec.last.headers["X-Requested-With"] == "XMLHttpRequest"

    async def test_non_200_returns_false(self):
        rec = _Recorder(status=500)
        async with _client(rec) as client:
            ok = await restrictions.close_dates("18330", "2026-03-01", "2026-03-02", client=client)
        assert ok is False

    async def test_unknown_category_name_raises(self):
        rec = _Recorder()
        async with _client(rec) as client:
            with pytest.raises(KeyError):
                await restrictions.close_dates(
                    "18330", "2026-03-01", "2026-03-02",
                    categories=["NoExiste"], client=client,
                )


class TestGetCategories:
    async def test_parses_option_labels(self):
        rec = _Recorder(html=RESTRICT_CALENDAR_HTML)
        async with _client(rec) as client:
            cats = await restrictions.get_categories("18330", client=client)
        assert cats == ["Matrimonial", "Triple"]
        assert rec.last.url.path == restrictions.RESTRICT_CALENDAR_URL

    async def test_missing_select_returns_empty(self):
        rec = _Recorder(html="<html><body>nada</body></html>")
        async with _client(rec) as client:
            assert await restrictions.get_categories("18330", client=client) == []


class TestCategoryIds:
    def test_known_categories_are_otelms_ids(self):
        assert restrictions.CATEGORY_IDS["Matrimonial"] == "13"
        assert restrictions.CATEGORY_IDS["Overbooking"] == "21"

    def test_all_ids_are_numeric(self):
        assert all(v.isdigit() for v in restrictions.CATEGORY_IDS.values())
