# src/services/data_service.py
from typing import Union, List, Dict, Any, Optional

from pyotels import OtelsExtractor, config, OtelsProcessadorData
from pyotels.logger import logger
from pyotels.models import ReservationDetail
from pyotels.utils.dev import save_html_debug


class DataService:

    def __init__(self, id_hotel: str, username: str, password: str,
                 use_cache: bool = False,
                 return_dict: bool = False,
                 headless: Optional[bool] = None):

        self.logger = logger(classname='DataService')

        self.username = username
        self.password = password
        self.id_hotel = id_hotel
        self.return_dict = return_dict

        self.domain = config.BASE_URL or "otelms.com"
        self.BASE_URL = f"https://{self.id_hotel}.{self.domain}"

        # Resolver headless: si es None, depende del modo debug (Debug=True -> Headless=False)
        is_headless = headless if headless is not None else not self.debug

        # Inicializar Extractor (Maneja Playwright y Sesión)
        self.extractor = OtelsExtractor(self.BASE_URL, headless=is_headless, use_cache=use_cache)
        self.procesator = OtelsProcessadorData()

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
        as_dict = self._resolve_as_dict(as_dict)

        self.logger.info()
        try:
            html_reservation_details = self.extractor.get_reservation_detail_html(reservation_id)
            save_html_debug(html_reservation_details, f"detail_{reservation_id}.html")





        except Exception as e:
            self.logger.error(f"Failed to fetch details for {reservation_id}: {e}")
            return None


if __name__ == '__main__':
    data = DataService()
    data.get_reservation_data()
