import asyncio
from datetime import datetime, timezone

import requests

from .config import config
from .logger import logger, log_execution
from .models import HtmlCache


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Maneja sesión, cookies y acceso autenticado.
    """

    BASE_URL: str = ...
    LOGIN_URL: str = ...
    CALENDAR_URL: str = ...
    DETAILS_URL: str = ...

    def __init__(self, id_hotel: str, username: str, password: str, debug: bool = False):
        self.debug = debug
        self.username = username
        self.password = password

        self.BASE_URL = f"https://{id_hotel}.{config.BASE_URL}"
        self.LOGIN_URL = f"{self.BASE_URL}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.BASE_URL}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.BASE_URL}/reservation_c2/folio/%s/1"

        # sesión persistente (mantiene cookies y headers)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": config.ACCEPT_REQUEST,
            "Referer": self.LOGIN_URL,
            "Origin": self.BASE_URL,
        })

    @log_execution
    async def login(self) -> bool:
        """Intenta hacer login en OtelMS."""
        payload = {
            "login": self.username,
            "password": self.password,
            "action": "login"
        }

        resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=20)
        html = resp.text.lower() if isinstance(resp, requests.Response) else resp.lower()
        is_success = False
        if isinstance(resp, requests.Response):
            if "url=/reservation_c2/calendar" in html or resp.status_code == 200:
                is_success = True
            elif "logout" in html:
                is_success = True
            elif resp.history and "index" in resp.url.lower():
                is_success = True
        else:
            # Verificación simplificada para contenido en caché
            if "url=/reservation_c2/calendar" in html or "logout" in html:
                is_success = True

        if is_success:
            logger.info("Login exitoso.")
            return True
        else:
            logger.warning("Login fallido. Verifique credenciales o respuesta del servidor.")
            return False

    @log_execution
    async def get_reservation_calendar(self) -> str:
        """Obtiene el HTML del calendario autenticado (con caché)."""
        # Ejecutamos la petición bloqueante en un hilo separado para no bloquear el loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_reservation_calendar)

    @log_execution
    async def _get_reservation_calendar(self) -> str:
        logger.info(f"Solicitando calendario: {self.CALENDAR_URL}")

        now = datetime.utcnow()

        html_cache = await HtmlCache.filter(
            expires_at__gt=now
        ).order_by('-created_at').first()

        if html_cache:
            html = html_cache.raw_html
            status_code = 200
        else:
            response = self.session.get(
                self.CALENDAR_URL,
                allow_redirects=True,
                timeout=20
            )
            status_code = response.status_code
            html = response.text

        if self.debug:
            self._debug("Calendar HTML", html)

        if status_code != 200:
            logger.error(f"Error obteniendo calendario. Status: {status_code}")
            raise RuntimeError(
                f"No se pudo obtener el calendario. Status: {status_code}"
            )

        return html

    @log_execution
    def get_page(self, url: str, save_prefix: str = "page") -> str:
        """
        Obtiene cualquier página interna y guarda el HTML si estamos en modo DEV.
        Útil para obtener detalles de reservas.
        """
        if not url.startswith("http"):
            url = f"{self.BASE_URL}{url}" if url.startswith("/") else f"{self.BASE_URL}/{url}"

        logger.info(f"Obteniendo página: {url}")
        resp = self.session.get(url, allow_redirects=True, timeout=20)

        if resp.status_code != 200:
            logger.error(f"Error obteniendo página: {resp.status_code}")
            return ""

        if config.DEBUG:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{save_prefix}_{timestamp}.html"
            output_path = config.get_output_path(filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(resp.text)
            logger.debug(f"HTML guardado en: {filename}")

        return resp.text

    @log_execution
    def get_reservation_details(self, reservation_id: str) -> str:
        """
        Obtiene el HTML de la página de detalles de una reserva.
        URL: /reservation_c2/folio/{reservation_id}/1
        """
        url = self.DETAILS_URL % reservation_id
        logger.info(f"Obteniendo detalles de reserva: {reservation_id}")

        resp = self.session.get(url, allow_redirects=True, timeout=20)

        if resp.status_code != 200:
            logger.error(f"Error obteniendo detalles ({reservation_id}): {resp.status_code}")
            return ""

        if self.debug:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"details_{reservation_id}_{timestamp}.html"
            output_path = config.get_output_path(filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(resp.text)
            logger.debug(f"HTML de detalles guardado en: {filename}")

        return resp.text

    def _debug(self, context: str, response: requests.Response):
        """Imprime información útil para depurar."""
        if config.DEBUG and config.DEBUG_REQUESTS:
            print("-" * 100)
            print(f"\n=== {context} ===")
            print("URL:", response.url)
            print("Status:", response.status_code)
            print("History:", [r.status_code for r in response.history])
            print("Cookies actuales:", self.session.cookies.get_dict())
            print("-" * 100)
