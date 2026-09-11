"""Tests de fetch_calendar_html con MockTransport (sin red)."""
import httpx
import pytest

from otelms.scraping.exceptions import AuthenticationError
from otelms.scraping.http_calendar import fetch_calendar_html

CAL_HTML = '<html><table class="calendar_table"><tr></tr></table></html>'


def make_transport(mode: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("do_single_login"):
            if mode == "bad_password":
                return httpx.Response(
                    200, text="<p>Credenciales incorrectas, intente de nuevo</p>",
                    request=request,
                )
            headers = [("Set-Cookie", "PHPSESSID=abc123; Path=/"),
                       ("Set-Cookie", "ci_session=xyz; Path=/")]
            return httpx.Response(200, text="ok", headers=headers, request=request)
        if path.endswith("single_login"):
            return httpx.Response(200, text="<form>login</form>")
        if path.endswith("calendar"):
            return httpx.Response(200, text=CAL_HTML, request=request)
        return httpx.Response(404, text="nf", request=request)

    return httpx.MockTransport(handler)


class TestFetchCalendarHtml:
    async def test_success(self):
        html = await fetch_calendar_html(
            "18330", "user", "pass", transport=make_transport("ok")
        )
        assert "calendar_table" in html

    async def test_bad_credentials(self):
        with pytest.raises(AuthenticationError):
            await fetch_calendar_html(
                "18330", "user", "wrong", transport=make_transport("bad_password")
            )
