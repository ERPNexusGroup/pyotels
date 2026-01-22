# src/pyotels/scarper.py
from typing import Optional, List, Dict, Union, Any

from . import config
from .data_processor import OtelsProcessadorData
from .exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError
from pyotels.utils.logger import get_logger
from .models import (
    CalendarReservation, CalendarCategories, ReservationModalDetail, ReservationDetail
)
from .services.data_service import OtelsDataServices
from .utils.dev import save_html_debug


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Orquesta la extracción (OtelsExtractor) y el procesamiento (OtelsProcessadorData).
    """

    def __init__(self, id_hotel: str, username: str, password: str,
                 use_cache: bool = False,
                 return_dict: bool = False,
                 headless: Optional[bool] = None):

        self.logger = get_logger(classname="OtelMSScraper")
        # self.debug = config.DEBUG
        self.username = username
        self.password = password
        self.id_hotel = id_hotel
        # self.return_dict = return_dict

        # self.domain = config.BASE_URL or "otelms.com"
        # self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"

        # Resolver headless: si es None, depende del modo debug (Debug=True -> Headless=False)
        is_headless = headless if headless is not None else not config.DEBUG

        # Inicializar Extractor (Maneja Playwright y Sesión)
        # self.extractor = OtelsExtractor(self.BASE_URL, headless=is_headless, use_cache=use_cache)
        self.service = OtelsDataServices(
            id_hotel=self.id_hotel,
            username=self.username,
            password=self.password,
            use_cache=use_cache,
            headless=is_headless,
            return_dict=return_dict
        )

    def login(self) -> bool:
        """
        Delega el login al extractor.
        """
        try:
            return self.service.extractor.login(
                # username=self.username,
                # password=self.password
            )
        except AuthenticationError:
            self.logger.error("Fallo en autenticación.")
            raise
        except Exception as e:
            self.logger.error(f"Error inesperado en login: {e}")
            raise NetworkError(f"Error en login: {e}")

    # def _resolve_as_dict(self, as_dict: Optional[bool]) -> bool:
    #     """Resuelve si se debe retornar un diccionario o un objeto."""
    #     return as_dict if as_dict is not None else self.return_dict

    def get_categories(self, target_date_str: str = None, as_dict: Optional[bool] = None) -> Union[
        CalendarCategories, Dict[str, Any]]:
        # as_dict = self._resolve_as_dict(as_dict)
        try:
            html_content = self.service.extractor.get_calendar_html(target_date_str)
            processor = OtelsProcessadorData(html_content)
            return processor.extract_categories(as_dict=as_dict)
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer categorías: {e}")

    def get_reservations(self, target_date_str: str = None, as_dict: Optional[bool] = None) -> Union[
        CalendarReservation, Dict[str, Any]]:
        # as_dict = self._resolve_as_dict(as_dict)
        try:
            html_content = self.service.extractor.get_calendar_html(target_date_str)
            save_html_debug(html_content, f"calendar_{target_date_str or 'default'}.html")
            processor = OtelsProcessadorData(html_content)
            return processor.extract_reservations(as_dict=as_dict)
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_reservations_ids(self, target_date_str: str = None) -> List[int]:
        try:
            ids_list = self.service.extractor.get_visible_reservation_ids()
            return ids_list
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_all_reservation_modals(self, as_dict: Optional[bool] = None) -> Union[
        List[ReservationModalDetail], List[Dict[str, Any]]]:
        # as_dict = self._resolve_as_dict(as_dict)
        try:
            html_content = self.service.extractor.collect_all_reservation_modals()
            processor = OtelsProcessadorData(html_content)
            return processor.extract_all_reservation_modals(as_dict=as_dict)
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer modales: {e}")

    def get_reservation_detail(self, reservation_id: Union[str, List[str]], as_dict: Optional[bool] = None) -> Union[
        ReservationDetail, List[ReservationDetail], Dict[str, Any], List[Dict[str, Any]], None]:
        """
        Obtiene los detalles de una o varias reservas.
        Si reservation_id es una lista, retorna una lista de detalles.
        Si es un solo ID, retorna un solo objeto detalle.
        """
        # as_dict = self._resolve_as_dict(as_dict)

        self.logger.info(f"Fetching details for reservation {reservation_id}")
        try:
            return self.service.get_reservation_data(
                reservation_id=reservation_id, as_dict=as_dict
            )
        except DataNotFoundError:
            self.logger.warning(f"Reserva {reservation_id} no encontrada.")
            return None
        except Exception as e:
            self.logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None

    def close(self):
        self.service.extractor.close()
        self.logger.info("Scraper cerrado.")
