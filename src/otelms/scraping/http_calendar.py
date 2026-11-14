"""
Calendario vía HTTP directo (sin browser).

El HTML del calendario es 100% server-rendered (incluye table.calendar_table,
items con resid, tooltips y availability sums), así que el sync de fase 1
(categorías + grilla de reservas) NO necesita Playwright: login POST + GET,
igual que OtelMSAuth._perform_login pero devolviendo el HTML crudo.

El browser queda reservado para acciones JS (fase 2+). El folio también
está server-rendered y se lee por HTTP: ver scraping/http_folio.py.
"""
import asyncio
import re

import httpx

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import settings
from otelms.scraping.exceptions import AuthenticationError
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

LOGIN_ERROR_KEYWORDS = ("incorrect", "error", "failed", "invalid", "inválido", "incorrecto")
TWOFA_MARKERS = ("2fa", "two-factor", "two_factor", "verification code", "otp", "challenge")
_META_REFRESH = re.compile(
    r"""<meta[^>]+http-equiv=['"]?refresh['"]?[^>]*content=['"][^'"]*url=([^'";]+)""",
    re.IGNORECASE,
)


def _meta_refresh_target(body: str) -> str | None:
    match = _META_REFRESH.search(body)
    return match.group(1).strip() if match else None


def _has_session_cookie(client: httpx.AsyncClient) -> bool:
    names = {c.name for c in client.cookies.jar}
    return bool(names & {"PHPSESSID", "ci_session"})


def _login_succeeded(resp: httpx.Response, client: httpx.AsyncClient) -> bool:
    """Éxito si hay cookie de sesión o la respuesta/landing no muestra formulario/error de login."""
    body = resp.text or ""
    body_lower = body.lower()
    if any(m in body_lower for m in TWOFA_MARKERS):
        return False
    if _has_session_cookie(client):
        return True
    landing = _meta_refresh_target(body)
    if landing and ("/reservation_c2/" in landing or "reservation_c2" in landing):
        return True
    if any(k in body_lower for k in LOGIN_ERROR_KEYWORDS):
        return False
    login_form_present = "do_single_login" in body_lower or "single_login" in body_lower
    # Página con meta-refresh legítimo de CodeIgniter u otra respuesta sin formulario de login
    if not login_form_present and resp.status_code < 400 and bool(body.strip()):
        return True
    return False


async def login_client(
    hotel_id: str,
    username: str,
    password: str,
    base_domain: str = "otelms.com",
    timeout_s: float = 60.0,
    transport: httpx.AsyncHTTPTransport | None = None,
) -> httpx.AsyncClient:
    """Login HTTP y devuelve el cliente ya autenticado.

    Va aparte del GET porque lo necesitan varias cosas con sesiones
    distintas: el calendario (una petición) y los folios de todas las
    reservas del día (una cada uno). Compartir la sesión evita repetir
    el login por cada folio, que es lo que hace que OtelMS tire la
    sesión a mitad de sincronización.

    La verificación TLS se deja activa a propósito: el certificado de
    desktop.otelms.com valida contra el CA store del sistema, comprobado
    tanto desde Windows como desde dentro del contenedor del worker. Si
    algún día deja de hacerlo, saltará el error de TLS y quedará a la
    vista en el log, que es justo lo que interesa.

    El cliente se devuelve abierto: quien lo reciba es dueño de cerrarlo.
    """
    urls = OtelMSUrls(base_domain, hotel_id)
    headers = {
        "User-Agent": settings.browser_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    client = httpx.AsyncClient(
        timeout=timeout_s, follow_redirects=True, headers=headers, transport=transport
    )
    try:
        resp = None
        for attempt in range(4):
            await client.get(urls.login_url)
            resp = await client.post(
                urls.do_login_url,
                data={"hotel": hotel_id, "login": username, "password": password, "action": "login"},
                headers={
                    "Referer": urls.login_url,
                    "Origin": urls.base_url,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if resp.status_code not in (429, 503) or attempt == 3:
                break
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else float(2 ** (attempt + 1))
            logger.warning("Login rate-limited, retrying", status=resp.status_code, delay_s=delay, hotel_id=hotel_id)
            await asyncio.sleep(min(delay, 15.0))

        assert resp is not None
        if resp.status_code >= 400:
            raise AuthenticationError(
                f"Login HTTP error: {resp.status_code}", hotel_id=hotel_id, url=urls.login_url
            )

        body_lower = (resp.text or "").lower()
        if any(m in body_lower for m in TWOFA_MARKERS):
            raise AuthenticationError(
                "2FA challenge detected (no soportado en sync HTTP)", hotel_id=hotel_id
            )

        # OtelMS puede responder 200 con meta-refresh al calendario (sesión válida)
        # o volver a mostrar el formulario/mensaje de error de login.
        if not _has_session_cookie(client) and any(k in body_lower for k in LOGIN_ERROR_KEYWORDS):
            raise AuthenticationError("Credenciales incorrectas", hotel_id=hotel_id)

        if not _login_succeeded(resp, client):
            raise AuthenticationError(
                "Sesión no válida tras login (redirect a login)", hotel_id=hotel_id
            )

        landing = _meta_refresh_target(resp.text or "")
        if landing:
            target = landing if landing.startswith("http") else f"{urls.base_url}{landing}"
            resp = await client.get(target)

        # Confirmación final: cookies o ausencia de formulario de login en landing
        final_body = (resp.text or "").lower()
        if not _has_session_cookie(client) and ("do_single_login" in final_body or "single_login" in final_body):
            raise AuthenticationError(
                "Sesión no válida tras login (redirect a login)", hotel_id=hotel_id
            )
    except BaseException:
        # El cliente ya está abierto y su __aexit__ no va a correr nunca,
        # así que si el login falla hay que cerrarlo a mano.
        await client.aclose()
        raise
    return client


async def fetch_calendar_html(
    hotel_id: str,
    username: str,
    password: str,
    base_domain: str = "otelms.com",
    target_date: str | None = None,
    timeout_s: float = 60.0,
    transport: httpx.AsyncHTTPTransport | None = None,
) -> str:
    """Login HTTP + GET del calendario. Retorna HTML crudo o lanza AuthenticationError."""
    urls = OtelMSUrls(base_domain, hotel_id)
    # El cliente viene ya abierto por login_client, así que no se puede
    # entrar con `async with` (httpx no admite abrirlo dos veces): se
    # cierra a mano.
    client = await login_client(
        hotel_id, username, password, base_domain, timeout_s, transport
    )
    try:
        cal = await client.get(urls.calendar_url(target_date))
        body_lower = (cal.text or "").lower()
        if (
            "single_login" in str(cal.url).lower()
            or "single_login" in cal.text[:2000]
            or "do_single_login" in body_lower
        ):
            raise AuthenticationError(
                "Sesión no válida tras login (redirect a login)", hotel_id=hotel_id
            )
        logger.info("Calendar fetched over HTTP", hotel_id=hotel_id, bytes=len(cal.text))
        return cal.text
    finally:
        await client.aclose()
