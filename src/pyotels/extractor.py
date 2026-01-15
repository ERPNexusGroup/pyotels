# src/pyotels/extractor.py
import time
import requests
from typing import Optional, Dict, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

from .logger import logger
from .exceptions import NetworkError, AuthenticationError
from .settings import config

class OtelsExtractor:
    """
    Extractor de HTML usando Playwright.
    Maneja la sesión, autenticación y navegación.
    """

    def __init__(self, base_url: str, headless: bool = True):
        self.headless = headless
        self.base_url = base_url
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.LOGIN_URL = f"{self.base_url}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.base_url}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.base_url}/reservation_c2/folio/%s/1"
        
        # Sesión de requests para login inicial (estrategia híbrida)
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": config.ACCEPT_REQUEST,
            "Connection": "keep-alive"
        })

    def start(self):
        """Inicializa los recursos de Playwright si no están activos."""
        if self.playwright: return
        
        logger.info("Iniciando Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        
        # Crear contexto con User-Agent definido
        self.context = self.browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = self.context.new_page()

    def login(self, username, password) -> bool:
        """
        Realiza el login en el sistema.
        Utiliza requests para la autenticación POST y transfiere cookies a Playwright.
        """
        self.start()
        logger.info(f"Iniciando login para {username} en {self.base_url}")
        
        payload = {"login": username, "password": password, "action": "login"}
        
        try:
            # Actualizar headers para el login
            self.session.headers.update({
                "Referer": self.LOGIN_URL,
                "Origin": self.base_url
            })
            
            resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
            resp.raise_for_status()

            # Verificar éxito del login
            if "login" not in resp.url:
                logger.info("✅ Login exitoso (Requests). Sincronizando cookies...")
                self._sync_cookies()
                return True

            # Buscar errores explícitos
            error_keywords = ["incorrect", "error", "failed", "invalid"]
            lower_text = resp.text.lower()
            if any(k in lower_text for k in error_keywords):
                raise AuthenticationError("Credenciales incorrectas o error en login.")

            logger.warning("⚠️ URL sigue siendo login, intentando sincronizar cookies de todos modos...")
            self._sync_cookies()
            
            # Verificación opcional: Navegar a una página protegida para confirmar
            # Por ahora asumimos True si no hubo error explícito
            return True

        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Error de conexión durante login: {e}")

    def _sync_cookies(self):
        """Transfiere las cookies de la sesión de requests al contexto de Playwright."""
        if not self.context: return
        
        req_cookies = self.session.cookies.get_dict()
        if req_cookies:
            domain = self.base_url.split('//')[-1].split('/')[0]
            pw_cookies = []
            for k, v in req_cookies.items():
                pw_cookies.append({
                    "name": k,
                    "value": v,
                    "domain": domain,
                    "path": "/"
                })
            self.context.add_cookies(pw_cookies)
            logger.debug(f"Cookies sincronizadas: {len(pw_cookies)}")

    def get_calendar_html(self, target_date_str: str = None) -> str:
        """
        Navega a la URL del calendario y extrae el HTML completo.
        """
        self.start()
        logger.info(f"Navegando al calendario: {self.CALENDAR_URL} (fecha: {target_date_str})")
        
        full_url = self.CALENDAR_URL
        if target_date_str:
            separator = '&' if '?' in self.CALENDAR_URL else '?'
            full_url = f"{self.CALENDAR_URL}{separator}date={target_date_str}"

        try:
            self.page.goto(full_url, wait_until="domcontentloaded", timeout=60000)
            
            # Validación de sesión en la página cargada
            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado (redirigido a login).")

            try:
                self.page.wait_for_selector("table.calendar_table", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout esperando tabla del calendario, intentando continuar con el HTML actual.")

            time.sleep(1) # Pequeña espera para scripts dinámicos
            return self.page.content()

        except PlaywrightTimeoutError:
            raise NetworkError("Timeout al cargar el calendario con Playwright.")
        except Exception as e:
            if isinstance(e, AuthenticationError): raise
            raise NetworkError(f"Error al obtener HTML del calendario: {e}")

    def get_reservation_detail_html(self, reservation_id: str) -> str:
        """
        Navega a la URL de detalle de reserva y extrae el HTML.
        """
        self.start()
        url = self.DETAILS_URL % reservation_id
        logger.info(f"Navegando a detalle de reserva: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado.")

            try:
                self.page.wait_for_selector("div.panel", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            return self.page.content()
        except Exception as e:
            if isinstance(e, AuthenticationError): raise
            raise NetworkError(f"Error al obtener HTML de detalle: {e}")

    def close(self):
        """Cierra todos los recursos."""
        if self.page: self.page.close()
        if self.context: self.context.close()
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        self.session.close()
        
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        logger.info("Recursos de Extractor cerrados.")
