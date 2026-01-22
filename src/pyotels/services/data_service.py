# src/services/data_service.py
from typing import Union, Dict, Any, Optional

from pyotels.core.models import ReservationDetail
from .. import OtelsExtractor, OtelsProcessadorData, ParsingError
from ..config.settings import config
from ..exceptions import DataNotFoundError
from ..utils.dev import save_html_debug
from ..utils.logger import get_logger


class OtelsDataServices:

    def __init__(self, id_hotel: str, username: str, password: str, use_cache: Optional[bool] = None,
                 return_dict: Optional[bool] = None, headless: Optional[bool] = None
                 ):

        self.logger = get_logger(classname='OtelsDataServices')

        self.username = username
        self.password = password
        self.id_hotel = id_hotel
        self.return_dict = return_dict

        self.domain = config.BASE_URL or "otelms.com"
        self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"

        # Resolver headless: si es None, depende del modo debug (Debug=True -> Headless=False)
        is_headless = headless if headless is not None else not config.DEBUG

        # Inicializar Extractor (Maneja Playwright y Sesión)
        self.extractor = OtelsExtractor(self.BASE_URL, username=username, password=password,
                                        headless=is_headless, use_cache=use_cache)
        self.processor = OtelsProcessadorData()

    # -------------------------------------------------
    #                  METODOS PRIVADOS               #
    # -------------------------------------------------

    def _resolve_as_dict(self, as_dict: Optional[bool]) -> bool:
        """Resuelve si se debe retornar un diccionario o un objeto."""
        return as_dict if as_dict is not None else self.return_dict

    # -------------------------------------------------
    #                  METODOS PUBLICOS               #
    # -------------------------------------------------
    def get_categories_data(self, start_date: Optional[str] = None, as_dict: Optional[bool] = None):
        """ Obtener la lista de categorias y habitaciones relacionadas"""
        try:
            html_content = self.extractor.get_calendar_html(start_date)
            processor = OtelsProcessadorData(html_content)
            return processor.extract_categories(as_dict=self._resolve_as_dict(as_dict))
        except Exception as e:
            self.logger.error(f"Error al extraer categorías: {e}")
            raise ParsingError(f"Error al extraer categorías: {e}")

    """
        Metodos para extraer los datos de la reserva
    """

    def _get_reservation_full_data(self, reservation_id: Optional[str] = None, as_dict: bool = False):
        html_reservation_details = self.extractor.get_reservation_detail_html(reservation_id)
        save_html_debug(html_reservation_details, f"detail_{reservation_id}.html")

        self.processor.html_content = html_reservation_details
        id_guest = self.processor.extract_guest_id()
        self.logger.debug(f"id_guest: {id_guest}")

        guest_html = self.extractor.get_guest_detail_html(id_guest)
        # self.logger.debug(f"guest_html: {guest_html}")
        guest = self.processor.extract_guest_details(guest_html, as_dict=as_dict)
        # 1. Información General (Basic Info)
        basic_info = self.processor.extract_basic_info_from_detail()
        self.logger.debug(f"basic_info: {basic_info}")

        for key in ['legal_entity', 'source', 'user']:
            val = basic_info.get(key)

            if isinstance(guest, dict):
                guest[key] = val
            else:
                setattr(guest, key, val)
        self.logger.debug(f"guest ({type(guest)}): {guest}")

        accommodation_html = self.extractor.get_reservation_accommodation_detail_html(reservation_id)
        # self.logger.debug(f"accommodation_html: {accommodation_html}")
        accommodation = self.processor.extract_accommodation_details(accommodation_html, as_dict=as_dict)
        self.logger.debug(f"accommodation ({type(accommodation)}): {accommodation}")

        guests = self.processor.extract_guests_list()
        self.logger.debug(f"guests ({len(guests)}): {guests}")

        services = self.processor.extract_services_list()
        self.logger.debug(f"services ({len(services)}): {services}")

        payments = self.processor.extract_payments_list()
        self.logger.debug(f"payments ({len(payments)}): {payments}")

        cars = self.processor.extract_cars_list()
        self.logger.debug(f"cars ({len(cars)}): {cars}")

        notes = self.processor.extract_notes_list()
        self.logger.debug(f"notes ({len(notes)}): {notes}")

        tariffs = self.processor.extract_daily_tariffs_list()
        self.logger.debug(f"tariffs ({len(tariffs)}): {tariffs}")

        logs = self.processor.extract_change_log_list()
        self.logger.debug(f"logs ({len(logs)}): {logs}")

        detail = ReservationDetail(
            reservation_number=reservation_id,
            guest=guest,
            accommodation=accommodation,
            guests=guests,
            services=services,
            payments=payments,
            cars=cars,
            notes=notes,
            daily_tariffs=tariffs,
            change_log=logs
        )
        return detail

    def _get_reservation_basic_data(self, as_dict: bool = False, start_date: Optional[str] = None) -> Union[
        ReservationDetail, Dict[str, Any], None]:
        html_content = self.extractor.get_calendar_html(start_date)
        save_html_debug(html_content, f"calendar_{start_date or 'default'}.html")
        processor = OtelsProcessadorData(html_content)
        return processor.extract_reservations(as_dict=self._resolve_as_dict(as_dict))

    def get_reservation_data(self, reservation_id: Optional[str] = None, full_data: bool = False,
                             as_dict: bool = False, start_date: Optional[str] = None) -> Union[
        ReservationDetail, Dict[str, Any], None]:
        """ obtener la data de cada segmento del detalle de las reservas """
        # Validar la devolucion de datos en objeto o diccionario
        return_dict = self._resolve_as_dict(as_dict)

        self.logger.info(f"Iniciando proceso de recuperacion de datos de reservacion 'get_reservation_data'")
        if reservation_id and not full_data:
            self.logger.warning("La configuracion de reservation_id y fulldata es incorrecta")
            return None

        try:
            reservations = self._get_reservation_full_data(
                reservation_id=reservation_id,
                as_dict=return_dict
            ) if full_data \
                else self._get_reservation_basic_data(
                as_dict=return_dict,
                start_date=start_date
            )
            return reservations
        except Exception as e:
            self.logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            raise DataNotFoundError(f"Failed to fetch details for {reservation_id}")

    """
        Metodos para extraer los ids
    """

    def get_ids_reservation(self,start_date: Optional[str] = None):
        return self.extractor.get_visible_reservation_ids(start_date)

