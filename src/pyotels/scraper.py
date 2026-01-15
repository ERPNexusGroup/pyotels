# src/pyotels/scarper.py
from typing import Optional

import diskcache as dc

from .extractor import OtelsExtractor
from .data_processor import OtelsProcessadorData
from .logger import logger, log_execution
from .models import (
    CalendarGrid, CalendarCategories, ReservationDetail
)
from .settings import config
from .exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError
from .utils.cache import get_cache_key
from .utils.dev import save_html_debug


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Orquesta la extracción (OtelsExtractor) y el procesamiento (OtelsProcessadorData).
    """

    def __init__(self, id_hotel: str, username: str, password: str):
        self.debug = config.DEBUG
        self.username = username
        self.password = password
        self.id_hotel = id_hotel
        
        self.domain = config.BASE_URL or "otelms.com"
        self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"
        
        # Inicializar Extractor (Maneja Playwright y Sesión)
        self.extractor = OtelsExtractor(self.BASE_URL, headless=not self.debug)

        # Configuración de caché
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

    # ---------------------------------------------------
    # Métodos Privado
    # ---------------------------------------------------
    def _fetch_calendar_html(self, target_date_str: str = None) -> str:
        """Obtiene HTML del calendario (con caché)."""
        params = {}
        if target_date_str: params['date'] = target_date_str

        # 1. Caché
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            # Nota: Usamos la URL del extractor para generar la key de caché
            # para mantener consistencia, aunque la URL es interna del extractor ahora.
            cache_key = get_cache_key(self.extractor.CALENDAR_URL, params)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        # 2. Extracción real
        try:
            html_content = self.extractor.get_calendar_html(target_date_str)

            # 3. Guardar en caché y debug
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            if self.debug:
                filename = f"calendar_{target_date_str or 'default'}.html"
                save_html_debug(html_content, filename)

            return html_content
        except Exception as e:
            raise NetworkError(f"Error al obtener calendario: {e}")
    # ---------------------------------------------------
    # Métodos Públicos
    # ---------------------------------------------------
    
    @log_execution
    def login(self) -> bool:
        """
        Delega el login al extractor.
        """
        try:
            return self.extractor.login(
                username=self.username,
                password=self.password
            )
        except AuthenticationError:
            logger.error("Fallo en autenticación.")
            raise
        except Exception as e:
            logger.error(f"Error inesperado en login: {e}")
            raise NetworkError(f"Error en login: {e}")

    def get_categories(self, target_date_str: str = None) -> CalendarCategories:
        try:
            html_content = self._fetch_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            return processor.extract_categories()
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer categorías: {e}")

    def get_grid(self, target_date_str: str = None) -> CalendarGrid:
        try:
            html_content = self._fetch_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            return processor.extract_grid()
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_reservation_detail(self, reservation_id: str) -> Optional[ReservationDetail]:
        logger.info(f"Fetching details for reservation {reservation_id}")
        
        try:
            html_content = self.extractor.get_reservation_detail_html(reservation_id)
            
            if self.debug:
                save_html_debug(html_content, f"detail_{reservation_id}.html")

            processor = OtelsProcessadorData(html_content)
            return processor.extract_reservation_details(html_content, reservation_id)
        except DataNotFoundError:
            logger.warning(f"Reserva {reservation_id} no encontrada (404/lógica).")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None

    def close(self):
        self.extractor.close()
        if self.cache: self.cache.close()
        logger.info("Scraper cerrado.")
