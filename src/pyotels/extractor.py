# src/pyotels/extractor.py
import time
import requests
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
import diskcache as dc

from .logger import get_logger
from .exceptions import NetworkError, AuthenticationError
from .settings import config
from .utils.cache import get_cache_key

class OtelsExtractor:
    """
    Extractor de HTML usando Playwright.
    Maneja la sesión, autenticación y navegación.
    """

    def __init__(self, base_url: str, headless: bool = True):
        self.logger = get_logger(classname='OtelsExtractor')
        self.headless = headless
        self.base_url = base_url
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.LOGIN_URL = f"{self.base_url}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.base_url}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.base_url}/reservation_c2/folio/%s/1"

        # Configuración de caché
        self._cache_enabled = config.DEBUG
        self._cache_duration = 60 * 60
        if self._cache_enabled:
            cache_dir = config.BASE_DIR / "cache"
            cache_dir.mkdir(exist_ok=True)
            self.cache = dc.Cache(str(cache_dir), timeout=self._cache_duration)
            self.logger.info(f"Cache de HTML habilitada en: {cache_dir}")
        else:
            self.cache = None
            self.logger.info("Cache de HTML deshabilitada.")

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
        
        self.logger.info("Iniciando Playwright...")
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
        self.logger.info(f"Iniciando login para {username} en {self.base_url}")
        
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
                self.logger.info("✅ Login exitoso (Requests). Sincronizando cookies...")
                self._sync_cookies()
                return True

            # Buscar errores explícitos
            error_keywords = ["incorrect", "error", "failed", "invalid"]
            lower_text = resp.text.lower()
            if any(k in lower_text for k in error_keywords):
                raise AuthenticationError("Credenciales incorrectas o error en login.")

            self.logger.warning("⚠️ URL sigue siendo login, intentando sincronizar cookies de todos modos...")
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
            self.logger.debug(f"Cookies sincronizadas: {len(pw_cookies)}")

    def get_calendar_html(self, target_date_str: str = None) -> str:
        """
        Navega a la URL del calendario y extrae el HTML completo.
        """
        params = {}

        if target_date_str: params['date'] = target_date_str
        # 1. Caché
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            # Nota: Usamos la URL del extractor para generar la key de caché
            # para mantener consistencia, aunque la URL es interna del extractor ahora.
            cache_key = get_cache_key(self.CALENDAR_URL, params)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Navegando al calendario: {self.CALENDAR_URL} (fecha: {target_date_str})")
        
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
                self.logger.warning("Timeout esperando tabla del calendario, intentando continuar con el HTML actual.")

            time.sleep(1) # Pequeña espera para scripts dinámicos

            html_content = self.page.content()

            # 3. Guardar en caché y debug
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content
        except PlaywrightTimeoutError:
            raise NetworkError("Timeout al cargar el calendario con Playwright.")
        except Exception as e:
            if isinstance(e, AuthenticationError): raise
            raise NetworkError(f"Error al obtener HTML del calendario: {e}")

    def get_reservation_detail_html(self, reservation_id: str) -> str:
        """
        Navega a la URL de detalle de reserva y extrae el HTML.
        """
        url = self.DETAILS_URL % reservation_id

        # 1. Verificar caché antes de navegar
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            cache_key = get_cache_key(url)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Navegando a detalle de reserva: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado.")

            try:
                self.page.wait_for_selector("div.panel", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            html_content = self.page.content()

            # 2. Guardar en caché
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content
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
        self.logger.info("Recursos de Extractor cerrados.")
