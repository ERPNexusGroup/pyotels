from datetime import datetime
import asyncio
import requests
from aiocache import cached
from .config import config


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

    def login(self) -> bool:
        """Intenta hacer login en OtelMS."""
        payload = {
            "login": self.username,
            "password": self.password,
            "action": "login"
        }

        resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=20)

        if self.debug:
            self._debug("Login", resp)

        html = resp.text.lower()

        # Login exitoso: detectamos redirección a /reservation_c2/calendar
        if "url=/reservation_c2/calendar" in html or resp.status_code == 200:
            print("[+] Login exitoso (meta redirect a calendar)")
            return True
        elif "logout" in html:
            print("[+] Login exitoso")
            return True
        elif resp.history and "index" in resp.url.lower():
            print("[+] Login exitoso (redirigido a dashboard)")
            return True
        else:
            print("[!] Login fallido")
            return False

    @cached(ttl=config.CACHE_TTL)
    async def get_reservation_calendar(self) -> str:
        """Obtiene el HTML del calendario autenticado (con caché)."""
        # Ejecutamos la petición bloqueante en un hilo separado para no bloquear el loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_reservation_calendar_sync)

    def _get_reservation_calendar_sync(self) -> str:
        """Método síncrono real para obtener el calendario."""
        resp = self.session.get(self.CALENDAR_URL, allow_redirects=True, timeout=20)
        print('get_reservation_calendar', resp.status_code)

        if self.debug:
            self._debug("Calendar", resp)

        if resp.status_code != 200:
            raise RuntimeError(f"No se pudo obtener el calendario. Status: {resp.status_code}")

        return resp.text

    def get_page(self, url: str, save_prefix: str = "page") -> str:
        """
        Obtiene cualquier página interna y guarda el HTML si estamos en modo DEV.
        Útil para obtener detalles de reservas.
        """
        if not url.startswith("http"):
            url = f"{self.BASE_URL}{url}" if url.startswith("/") else f"{self.BASE_URL}/{url}"

        print(f"[Scraper] Obteniendo: {url}")
        resp = self.session.get(url, allow_redirects=True, timeout=20)

        if resp.status_code != 200:
            print(f"[!] Error obteniendo página: {resp.status_code}")
            return ""

        if config.DEBUG:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{save_prefix}_{timestamp}.html"
            output_path = config.get_output_path(filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(resp.text)
            print(f"[DEV] HTML guardado en: {filename}")

        return resp.text

    def _debug(self, context: str, response: requests.Response):
        """Imprime información útil para depurar."""
        print(f"\n[DEBUG] === {context} ===")
        print("URL:", response.url)
        print("Status:", response.status_code)
        print("History:", [r.status_code for r in response.history])
        print("Cookies actuales:", self.session.cookies.get_dict())
        print("-" * 60)
        text_preview = response.text[:500].replace("\n", " ")
        print("HTML (preview):", text_preview)
        print("=" * 60, "\n")
