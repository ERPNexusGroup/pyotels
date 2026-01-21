# src/services/data_service.py
import sys
from typing import Union, List, Dict, Any, Optional

from pyotels import OtelsExtractor, OtelsProcessadorData, AuthenticationError, NetworkError
from pyotels.models import ReservationDetail
from pyotels.settings import config
from pyotels.utils.dev import save_html_debug
from src.pyotels.logger import get_logger


class DataService:

    def __init__(self, id_hotel: str, username: str, password: str,
                 use_cache: bool = False,
                 return_dict: bool = False,
                 headless: Optional[bool] = None):

        self.logger = get_logger(classname='DataService')

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
    def get_reservation_data(self, reservation_id: Union[str, List[str]], as_dict: bool = False) -> Union[
        ReservationDetail, Dict[str, Any], List[Dict[str, Any]], None]:
        # Validar la devolucion de datos en objeto o diccionario
        return_dict = self._resolve_as_dict(as_dict)

        self.logger.info(f"Iniciando proceso de recuperacion de datos de reservacion 'get_reservation_data'")
        try:
            html_reservation_details = self.extractor.get_reservation_detail_html(reservation_id)
            save_html_debug(html_reservation_details, f"detail_{reservation_id}.html")

            self.processor.html_content = html_reservation_details
            id_guest = self.processor.extract_guest_id()
            self.logger.debug(f"id_guest: {id_guest}")

            guest_html = self.extractor.get_guest_detail_html(id_guest)
            self.logger.debug(f"guest_html: {guest_html}")
            guest = self.processor.extract_guest_details(guest_html, as_dict=return_dict)
            # 1. Información General (Basic Info)
            basic_info = self.processor.extract_basic_info_from_detail(html_reservation_details)
            self.logger.debug(f"basic_info: {basic_info}")

            for key in ['legal_entity', 'source', 'user']:
                val = basic_info.get(key)

                if isinstance(guest, dict):
                    guest[key] = val
                else:
                    setattr(guest, key, val)
            self.logger.debug(f"guest: {guest}")

            # accommodation_html = self.extractor.get_reservation_accommodation_detail_html(reservation_id)
            # accommodation = self.processor.extract_accommodation_details(accommodation_html, as_dict=return_dict)
            # self.logger.debug(f"accommodation: {accommodation}\n Type: {type(accommodation)}")
            sys.exit()

            detail = ReservationDetail(
                reservation_number=reservation_id,
                guests=guest,
                accommodation=accommodation,
                # services=services,
                # payments=payments,
                # cars=cars,
                # notes=notes,
                # daily_tariffs=tariffs,
                # change_log=logs
            )
            return None
        except Exception as e:
            self.logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None


if __name__ == '__main__':
    id_hotel = '118510'
    username = 'gerencia@harmonyhotelgroup.com'
    password = 'Majestic2'

    data = DataService(id_hotel, username, password)
    # Fragmento temporal:
    try:
        data.extractor.login()
    except AuthenticationError:
        data.logger.error("Fallo en autenticación.")
        raise
    except Exception as e:
        data.logger.error(f"Error inesperado en login: {e}")
        raise NetworkError(f"Error en login: {e}")

    data.get_reservation_data(22810)
