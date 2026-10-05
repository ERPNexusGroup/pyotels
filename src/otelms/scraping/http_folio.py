"""
Folio de reserva vía HTTP directo (sin browser).

El folio es lo único que trae los consumos y los pagos. El modal que
abre el calendario es solo un resumen (huésped, fechas, tarifa, saldo),
así que pedir el detalle por modal nunca devolverá services ni
payments: hay que ir a /reservation_c2/folio/{id}.

El HTML es server-rendered igual que el calendario, así que tampoco
necesita Playwright. Se hace login una vez y se reutiliza la sesión
para todos los folios del hotel: entrar por cada reserva multiplicaría
los logins por el número de reservas del día.

Ver docs/otelms_endpoints.md §3 para el desglose de las 11 tablas del
folio y el significado real de sus columnas.
"""
import asyncio

import httpx

from otelms.config.constants import OtelMSUrls
from otelms.scraping.exceptions import AuthenticationError
from otelms.scraping.http_calendar import login_client
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

# El folio devuelve 200 con el HTML de login si la sesión caducó, así que
# el código HTTP no sirve para detectarlo: hay que mirar el contenido.
SESSION_LOST_MARKER = "single_login"


class FolioClient:
    """Sesión HTTP autenticada contra OtelMS para leer folios.

    Uno por hotel y por sincronización: la sesión caduca, y mantenerla
    abierta entre syncs acabaría pidiendo un folio y recibiéndolo con la
    página de login metida dentro.
    """

    def __init__(
        self,
        hotel_id: str,
        username: str,
        password: str,
        base_domain: str = "otelms.com",
        timeout_s: float = 60.0,
        transport: httpx.AsyncHTTPTransport | None = None,
    ) -> None:
        self.hotel_id = hotel_id
        self._username = username
        self._password = password
        self._base_domain = base_domain
        self._timeout_s = timeout_s
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "FolioClient":
        await self.login()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def login(self) -> None:
        """Abre sesión y autentica. Lanza AuthenticationError si falla."""
        if self._client is not None:
            return
        self._client = await login_client(
            self.hotel_id,
            self._username,
            self._password,
            self._base_domain,
            self._timeout_s,
            self._transport,
        )
        logger.info("Folio client logged in", hotel_id=self.hotel_id)

    async def fetch(self, reservation_id: str) -> str | None:
        """Devuelve el HTML del folio, o None si no se pudo leer.

        None y no una excepción: que un folio falle no debe tumbar el
        sync entero, porque las demás reservas del día sí se pueden
        guardar. Lo que se pierde es ese folio, no las otras.
        """
        if self._client is None:
            await self.login()
        assert self._client is not None  # para mypy tras el login

        url = OtelMSUrls(self._base_domain, self.hotel_id).reservation_detail_url(
            reservation_id
        )
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            logger.warning(
                "Folio request failed",
                hotel_id=self.hotel_id,
                reservation_id=reservation_id,
                error=str(exc),
            )
            return None

        if resp.status_code >= 400:
            logger.warning(
                "Folio returned error status",
                hotel_id=self.hotel_id,
                reservation_id=reservation_id,
                status=resp.status_code,
            )
            return None

        # La sesión caducada devuelve 200 con el formulario de login dentro.
        if SESSION_LOST_MARKER in str(resp.url).lower() or (
            SESSION_LOST_MARKER in resp.text[:2000]
        ):
            logger.warning(
                "Session lost while reading folio",
                hotel_id=self.hotel_id,
                reservation_id=reservation_id,
            )
            return None

        logger.info(
            "Folio fetched over HTTP",
            hotel_id=self.hotel_id,
            reservation_id=reservation_id,
            bytes=len(resp.text),
        )
        return resp.text

    async def fetch_many(
        self,
        reservation_ids: list[str],
        delay_s: float = 0.3,
    ) -> dict[str, str]:
        """Descarga varios folios, dejándose fuera los que fallen.

        El retardo entre peticiones es a propósito: son del orden de 13
        folios de ~180 KB seguidos contra el mismo portal, y es el ritmo
        que se ha sostenido en los scripts manuales sin que la sesión
        salte a mitad.
        """
        out: dict[str, str] = {}
        for res_id in reservation_ids:
            html = await self.fetch(res_id)
            if html:
                out[res_id] = html
            if delay_s:
                await asyncio.sleep(delay_s)
        return out

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None


__all__ = ["AuthenticationError", "FolioClient"]
