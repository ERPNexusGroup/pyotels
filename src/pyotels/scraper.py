# src/pyotels/scarper.py
from typing import Optional

from .extractor import OtelsExtractor
from .data_processor import OtelsProcessadorData
from .logger import get_logger, log_execution
from .models import (
    CalendarGrid, CalendarCategories, ReservationDetail
)
from .settings import config
from .exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError

from .utils.dev import save_html_debug


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Orquesta la extracción (OtelsExtractor) y el procesamiento (OtelsProcessadorData).
    """

    def __init__(self, id_hotel: str, username: str, password: str):
        self.logger = get_logger(classname="OtelMSScraper")
        self.debug = config.DEBUG
        self.username = username
        self.password = password
        self.id_hotel = id_hotel

        self.domain = config.BASE_URL or "otelms.com"
        self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"
        
        # Inicializar Extractor (Maneja Playwright y Sesión)
        self.extractor = OtelsExtractor(self.BASE_URL, headless=not self.debug)

    # ---------------------------------------------------
    # Métodos Privado
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
            self.logger.error("Fallo en autenticación.")
            raise
        except Exception as e:
            self.logger.error(f"Error inesperado en login: {e}")
            raise NetworkError(f"Error en login: {e}")

    def get_categories(self, target_date_str: str = None) -> CalendarCategories:
        try:
            html_content = self.extractor.get_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            return processor.extract_categories()
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer categorías: {e}")

    def get_reservations(self, target_date_str: str = None) -> CalendarGrid:
        try:
            html_content = self.extractor.get_calendar_html(target_date_str)
            save_html_debug(html_content, f"calendar_{target_date_str or 'default'}.html")
            processor = OtelsProcessadorData(html_content)
            return processor.extract_grid()
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_reservation_detail(self, reservation_id: str) -> Optional[ReservationDetail]:
        self.logger.info(f"Fetching details for reservation {reservation_id}")
        
        try:
            html_content = self.extractor.get_reservation_detail_html(reservation_id)

            save_html_debug(html_content, f"detail_{reservation_id}.html")

            processor = OtelsProcessadorData(html_content)
            return processor.extract_reservation_details(html_content, reservation_id)
        except DataNotFoundError:
            self.logger.warning(f"Reserva {reservation_id} no encontrada (404/lógica).")
            return None
        except Exception as e:
            self.logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None

    def close(self):
        self.extractor.close()
        self.logger.info("Scraper cerrado.")
