"""Tests de FolioClient con MockTransport (sin red)."""
import httpx
import pytest

from otelms.scraping.exceptions import AuthenticationError
from otelms.scraping.http_folio import FolioClient

FOLIO_HTML = "<html><body><table><tr><td>folio</td></tr></table></body></html>"


def make_transport(
    mode: str = "ok",
    requested: list[str] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if requested is not None and "/folio/" in path:
            requested.append(path)
        if path.endswith("do_single_login"):
            if mode == "bad_password":
                return httpx.Response(
                    200,
                    text="<p>Credenciales incorrectas, intente de nuevo</p>",
                    request=request,
                )
            return httpx.Response(200, text="ok", request=request)
        if path.endswith("single_login"):
            return httpx.Response(200, text="<form>login</form>", request=request)
        if "/folio/" in path:
            if mode == "http_error":
                return httpx.Response(500, text="boom", request=request)
            if mode == "session_lost":
                # Lo que hace OtelMS cuando la sesión caduca: 200 con el
                # formulario de login dentro, no un 401.
                return httpx.Response(200, text="<form>single_login</form>", request=request)
            if mode == "network_error":
                raise httpx.ConnectError("sin conexión", request=request)
            return httpx.Response(200, text=FOLIO_HTML, request=request)
        return httpx.Response(404, text="nf", request=request)

    return httpx.MockTransport(handler)


class TestFolioClient:
    async def test_descarga_un_folio(self):
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("ok")
        ) as client:
            html = await client.fetch("23564")
        assert html == FOLIO_HTML

    async def test_descarga_varios(self):
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("ok")
        ) as client:
            folios = await client.fetch_many(["1", "2", "3"], delay_s=0)
        assert set(folios) == {"1", "2", "3"}

    async def test_hace_un_solo_login_para_todos_los_folios(self):
        """Entrar por cada folio multiplicaría los logins por el número de
        reservas y es lo que hace que OtelMS corte la sesión."""
        logins: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("do_single_login"):
                logins.append(request.url.path)
                return httpx.Response(200, text="ok", request=request)
            if request.url.path.endswith("single_login"):
                return httpx.Response(200, text="<form>login</form>", request=request)
            return httpx.Response(200, text=FOLIO_HTML, request=request)

        async with FolioClient(
            "18330", "user", "pass", transport=httpx.MockTransport(handler)
        ) as client:
            await client.fetch_many(["1", "2", "3", "4", "5"], delay_s=0)

        assert len(logins) == 1

    async def test_login_fallido_no_deja_cliente_abierto(self):
        with pytest.raises(AuthenticationError):
            async with FolioClient(
                "18330", "user", "wrong", transport=make_transport("bad_password")
            ):
                pass

    async def test_un_folio_que_falla_no_tumba_el_resto(self):
        """Lo que se pierde es ese folio, no las demás reservas del día."""
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("http_error")
        ) as client:
            folios = await client.fetch_many(["1", "2"], delay_s=0)
        assert folios == {}

    async def test_sesion_caducada_se_detecta_por_contenido(self):
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("session_lost")
        ) as client:
            html = await client.fetch("23564")
        assert html is None

    async def test_error_de_red_se_traga(self):
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("network_error")
        ) as client:
            assert await client.fetch("23564") is None

    async def test_fetch_sin_login_previo(self):
        """fetch() debe autenticar solo si no hay sesión: llamarlo sin
        entrar antes es el uso normal desde el sync."""
        async with FolioClient(
            "18330", "user", "pass", transport=make_transport("ok")
        ):
            pass  # el __aenter__ ya autenticó

    async def test_reutiliza_la_sesion_entre_folios(self):
        requested: list[str] = []
        async with FolioClient(
            "18330",
            "user",
            "pass",
            transport=make_transport("ok", requested=requested),
        ) as client:
            await client.fetch_many(["111", "222"], delay_s=0)
        assert requested == [
            "/reservation_c2/folio/111/1",
            "/reservation_c2/folio/222/1",
        ]