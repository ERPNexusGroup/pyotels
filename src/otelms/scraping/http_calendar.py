"""
Calendario vía HTTP directo (sin browser).

El HTML del calendario es 100% server-rendered (incluye table.calendar_table,
items con resid, tooltips y availability sums), así que el sync de fase 1
(categorías + grilla de reservas) NO necesita Playwright: login POST + GET,
igual que OtelMSAuth._perform_login pero devolviendo el HTML crudo.

El browser queda reservado para folio/detalles/acciones JS (fase 2+).
"""
import httpx

from otelms.config.constants import OtelMSUrls
from otelms.scraping.exceptions import AuthenticationError
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

LOGIN_ERROR_KEYWORDS = ("incorrect", "error", "failed", "invalid", "inválido", "incorrecto")
TWOFA_MARKERS = ("2fa", "two-factor", "two_factor", "verification code", "otp", "challenge")


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
    headers = {
        "User-Agent": "pyotels/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        verify=False, timeout=timeout_s, follow_redirects=True, headers=headers,
        transport=transport,
    ) as client:
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
        if resp.status_code >= 400:
            raise AuthenticationError(
                f"Login HTTP error: {resp.status_code}", hotel_id=hotel_id, url=urls.login_url
            )
        body_lower = resp.text.lower()
        if any(m in body_lower for m in TWOFA_MARKERS):
            raise AuthenticationError("2FA challenge detected (no soportado en sync HTTP)", hotel_id=hotel_id)
        if "login" in str(resp.url).lower() and any(k in body_lower for k in LOGIN_ERROR_KEYWORDS):
            raise AuthenticationError("Credenciales incorrectas", hotel_id=hotel_id)

        cal = await client.get(urls.calendar_url(target_date))
        if "single_login" in str(cal.url).lower() or "single_login" in cal.text[:2000]:
            raise AuthenticationError(
                "Sesión no válida tras login (redirect a login)", hotel_id=hotel_id
            )
        logger.info("Calendar fetched over HTTP", hotel_id=hotel_id, bytes=len(cal.text))
        return cal.text
