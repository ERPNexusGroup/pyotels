# src/pyotels/scarper.py
from typing import Optional, List, Dict, Union, Any

from pyotels.core.data_processor import OtelsProcessadorData
from pyotels.core.models import (
    CalendarReservation, CalendarCategories, ReservationModalDetail, ReservationDetail
)
from pyotels.utils.logger import get_logger
from . import config
from .exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError
from .services.data_service import OtelsDataServices


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Orquesta la extracción (OtelsExtractor) y el procesamiento (OtelsProcessadorData).
    """

    def __init__(self, id_hotel: str, username: str, password: str,
                 use_cache: Optional[bool] = None,
                 return_dict: Optional[bool] = None,
                 headless: Optional[bool] = None):

        self.logger = get_logger(classname="OtelMSScraper")
        self.username = username
        self.password = password
        self.id_hotel = id_hotel

        # Inicializar Extractor (Maneja Playwright y Sesión)
        # self.extractor = OtelsExtractor(self.BASE_URL, headless=is_headless, use_cache=use_cache)
        self.service = OtelsDataServices(
            id_hotel=self.id_hotel,
            username=self.username,
            password=self.password,
            use_cache=use_cache if use_cache is not None else config.USE_CACHE,
            headless=headless if headless is not None else config.HEADLESS,
            return_dict=return_dict if return_dict is not None else config.RETURN_DICT
        )

    def login(self) -> bool:
        """
        Delega el login al extractor.
        """
        try:
            return self.service.extractor.login()
        except AuthenticationError:
            self.logger.error("Fallo en autenticación.")
            raise
        except Exception as e:
            self.logger.error(f"Error inesperado en login: {e}")
            raise NetworkError(f"Error en login: {e}")

    def get_categories(self, as_dict: Optional[bool] = None) -> Union[CalendarCategories, Dict[str, Any]]:
        try:
            return self.service.get_categories_data(as_dict=as_dict)
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer categorías: {e}")

    def get_reservations(self, start_date: Optional[str] = None, as_dict: Optional[bool] = None,
                         full_data: Optional[bool] = False) -> Union[
        CalendarReservation, Dict[str, Any]]:
        try:
            return self.service.get_reservation_data(as_dict=as_dict, start_date=start_date, full_data=full_data)
        except Exception as e:
            if isinstance(e, (NetworkError, AuthenticationError)): raise
            raise ParsingError(f"Error al extraer grilla: {e}")

    def get_ids_reservation(self, target_date_str: str = None) -> List[int]:
        try:
            return self.service.get_ids_reservation(target_date_str)
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
        self.logger.debug(f"Method: get_reservation_detail")
        self.logger.debug(f"Parameters: {{\"reservation_id\": {reservation_id}, \"as_dict\": {as_dict}}}")

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
