# src/pyotels/scarper.py
import datetime
from typing import List, Optional

import diskcache as dc
import requests
from playwright.sync_api import Browser, Page, sync_playwright, TimeoutError as PlaywrightTimeoutError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .extractor import OtelsExtractor
from .data_processor import OtelsProcessadorData
from .logger import logger, log_execution
from .models import (
    CalendarGrid, CalendarCategories, ReservationDetail, CalendarData
)
from .settings import config
from .exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError
from .utils.cache import get_cache_key
from .utils.dev import save_html_debug


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    """

    def __init__(self, id_hotel: str, username: str, password: str, debug: bool = False):
        self.debug = debug
        self.username = username
        self.password = password

        self.id_hotel = id_hotel
        self.domain = config.BASE_URL
        self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"

        self.LOGIN_URL = f"{self.BASE_URL}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.BASE_URL}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.BASE_URL}/reservation_c2/folio/%s/1"

        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)

        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": config.ACCEPT_REQUEST,
            "Referer": self.LOGIN_URL,
            "Origin": self.BASE_URL,
            "Connection": "keep-alive"
        })

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._playwright_context_initialized = False
        self._extractor: Optional[OtelsExtractor] = None

        self._cache_enabled = config.DEBUG
        self._cache_duration = 60 * 60
        if self._cache_enabled:
            cache_dir = config.BASE_DIR / "cache"
            cache_dir.mkdir(exist_ok=True)
            self.cache = dc.Cache(str(cache_dir), timeout=self._cache_duration)
            logger.info(f"Cache de HTML habilitada en: {cache_dir}")
        else:
            self.cache = None
            logger.info("Cache de HTML deshabilitada.")

        self.day_id_to_date_map = {}

    def _get_extractor(self) -> OtelsExtractor:
        """Obtiene o inicializa el extractor de Playwright."""
        self._ensure_playwright_context()
        if not self._extractor:
            self._extractor = OtelsExtractor(self.page)
        return self._extractor

    def _fetch_calendar_html(self, target_date_str: str = None) -> str:
        """Helper para obtener el HTML del calendario con soporte de caché y Playwright."""
        params = {}
        if target_date_str:
            params['date'] = target_date_str
            
        # 1. Intentar obtener de caché
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            cache_key = get_cache_key(self.CALENDAR_URL, params)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        logger.info(f"Fetching calendar HTML (date={target_date_str})...")
        try:
            # Usar Playwright para obtener el HTML
            extractor = self._get_extractor()
            html_content = extractor.get_calendar_html(self.CALENDAR_URL, target_date_str)
            
            # Validación simple de sesión expirada (aunque Playwright maneja cookies, es bueno verificar)
            if "login" in self.page.url or "DoLogIn" in html_content:
                 # Intentar relogin si es necesario, o lanzar error
                 # Por simplicidad lanzamos error y dejamos que el llamador maneje reintentos si implementa lógica superior
                raise AuthenticationError("La sesión ha expirado o no es válida.")
            
            # 2. Guardar en caché y debug
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)
            
            if self.debug:
                filename = f"calendar_{target_date_str or 'default'}.html"
                save_html_debug(html_content, filename)
                
            return html_content
        except Exception as e:
            raise NetworkError(f"Error al obtener calendario: {e}")

    @log_execution
    def login(self) -> bool:
        """
        Realiza el login usando requests para obtener cookies iniciales, 
        luego inicializa Playwright.
        """
        logger.info(f"Iniciando login para {self.username} en {self.id_hotel}")
        payload = {"login": self.username, "password": self.password, "action": "login"}
        try:
            resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
            resp.raise_for_status()

            if "login" not in resp.url:
                logger.info("✅ Login exitoso (Redirección correcta).")
                self._ensure_playwright_context() # Sincronizar cookies con Playwright
                return True

            error_keywords = ["incorrect", "error", "failed", "invalid"]
            lower_text = resp.text.lower()
            
            if any(k in lower_text for k in error_keywords):
                raise AuthenticationError("Credenciales incorrectas o error en login.")

            logger.warning("⚠️ URL sigue siendo login, verificando acceso...")
            # Verificación secundaria podría hacerse con requests o playwright
            # Aquí asumimos éxito si no hay error explícito y procedemos
            self._ensure_playwright_context()
            return True
            
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Error de conexión durante login: {e}")

    def get_categories(self, target_date_str: str = None) -> CalendarCategories:
        try:
            html_content = self._fetch_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            categories_data = processor.extract_categories()
            return categories_data
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)):
                raise
            raise ParsingError(f"Error al extraer categorías: {e}")

    def get_grid(self, target_date_str: str = None) -> CalendarGrid:
        try:
            html_content = self._fetch_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            grid_data = processor.extract_grid()
            return grid_data
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)):
                raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_reservation_detail(self, reservation_id: str) -> Optional[ReservationDetail]:
        url = self.DETAILS_URL % reservation_id
        logger.info(f"Fetching details for reservation {reservation_id}")
        
        try:
            extractor = self._get_extractor()
            html_content = extractor.get_reservation_detail_html(url)
            
            if self.debug:
                save_html_debug(html_content, f"detail_{reservation_id}.html")

            processor = OtelsProcessadorData(html_content)
            detail = processor.extract_reservation_details(html_content, reservation_id)
            return detail
        except Exception as e:
            logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None

    # --- Playwright & Auth Methods ---

    def _ensure_playwright_context(self):
        if self._playwright_context_initialized: return
        logger.info("Inicializando contexto de Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.browser or self.playwright.chromium.launch(headless=not config.DEBUG)
        self.page = self.page or self.browser.new_page()
        
        # Transferir cookies de requests a playwright
        req_cookies = self.session.cookies.get_dict()
        if req_cookies:
            pw_cookies = []
            domain = self.BASE_URL.split('//')[-1].split('/')[0] # extraer dominio limpio
            for k, v in req_cookies.items():
                pw_cookies.append({
                    "name": k, 
                    "value": v, 
                    "domain": domain, 
                    "path": "/"
                })
            self.page.context.add_cookies(pw_cookies)
            
        self._playwright_context_initialized = True

    def close(self):
        if self.page: self.page.close()
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        self._playwright_context_initialized = False
        self._extractor = None
        self.session.close()
        logger.info("Recursos cerrados.")
