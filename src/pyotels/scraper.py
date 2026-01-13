from datetime import datetime
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .settings import config
from .logger import logger, log_execution

class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Maneja sesión, cookies y acceso autenticado.
    """

    BASE_URL: str = ...
    LOGIN_URL: str = ...
    CALENDAR_URL: str = ...
    DETAILS_URL: str = ...

    def __init__(self, id_hotel: str, username: str, password: str, debug: bool = False):
        self.debug = debug
        self.username = username
        self.password = password

        self.BASE_URL = f"https://{id_hotel}.{config.BASE_URL}"
        self.LOGIN_URL = f"{self.BASE_URL}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.BASE_URL}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.BASE_URL}/reservation_c2/folio/%s/1"

        # TODO: Implementacion a futuro (No eliminar)
        href = "/reservation_c2/set_checkin/22745/status"

        #TODO: antes de llegar al checkout esta de actualizar el estatus de las fechas a la primera pantalla (No Eliminar)
        href = "/reservation_c2/set_checkout/22745/status"

        #TODO: Para abrir y cerrar fechas y habitaciones (No Eliminar)
        onclick = "close_save(&quot;/reservation_c2/days_close_save&quot;)"
        onclick = "open_save(&quot;/reservation_c2/days_open_save&quot;)"


        # sesión persistente (mantiene cookies y headers)
        self.session = requests.Session()
        
        # Configurar estrategia de reintentos
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": config.ACCEPT_REQUEST,
            "Referer": self.LOGIN_URL,
            "Origin": self.BASE_URL,
            "Connection": "keep-alive"
        })

    @log_execution
    def login(self) -> bool:
        """Intenta hacer login en OtelMS."""
        payload = {
            "login": self.username,
            "password": self.password,
            "action": "login"
        }

        try:
            resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
            html = resp.text.lower()
            is_success = False
            if "url=/reservation_c2/calendar" in html or resp.status_code == 200:
                is_success = True
            elif "logout" in html:
                is_success = True
            elif resp.history and "index" in resp.url.lower():
                is_success = True

            if is_success:
                logger.info("Login exitoso.")
                return True
            else:
                logger.warning("Login fallido. Verifique credenciales o respuesta del servidor.")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión durante login: {e}")
            return False

    @log_execution
    def get_reservation_calendar(self) -> str:
        """Obtiene el HTML del calendario autenticado."""
        logger.info(f"Solicitando calendario: {self.CALENDAR_URL}")

        try:
            response = self.session.get(
                self.CALENDAR_URL,
                allow_redirects=True,
                timeout=30
            )
            status_code = response.status_code
            html = response.text

            if self.debug:
                self._debug("Calendar HTML", response)

            if status_code != 200:
                logger.error(f"Error obteniendo calendario. Status: {status_code}")
                raise RuntimeError(
                    f"No se pudo obtener el calendario. Status: {status_code}"
                )

            return html
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión obteniendo calendario: {e}")
            raise

    @log_execution
    def get_page(self, url: str) -> str:
        """
        Obtiene cualquier página interna.
        Útil para obtener detalles de reservas.
        """
        if not url.startswith("http"):
            url = f"{self.BASE_URL}{url}" if url.startswith("/") else f"{self.BASE_URL}/{url}"

        logger.info(f"Obteniendo página: {url}")
        try:
            resp = self.session.get(url, allow_redirects=True, timeout=30)

            if resp.status_code != 200:
                logger.error(f"Error obteniendo página: {resp.status_code}")
                return ""

            return resp.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión obteniendo página {url}: {e}")
            return ""

    @log_execution
    def get_reservation_details(self, reservation_id: str) -> str:
        """
        Obtiene el HTML de la página de detalles de una reserva.
        URL: /reservation_c2/folio/{reservation_id}/1
        """
        url = self.DETAILS_URL % reservation_id
        logger.info(f"Obteniendo detalles de reserva: {reservation_id}")

        try:
            # Aumentamos timeout y usamos la sesión con reintentos configurados
            resp = self.session.get(url, allow_redirects=True, timeout=30)

            if resp.status_code != 200:
                logger.error(f"Error obteniendo detalles ({reservation_id}): {resp.status_code}")
                return ""

            return resp.text
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Conexión abortada para reserva {reservation_id}, reintentando una vez más tras pausa...")
            time.sleep(2)
            try:
                # Reintento manual simple si falla la conexión
                resp = self.session.get(url, allow_redirects=True, timeout=30)
                if resp.status_code != 200:
                    logger.error(f"Error en reintento ({reservation_id}): {resp.status_code}")
                    return ""
                return resp.text
            except Exception as e2:
                logger.error(f"Fallo definitivo obteniendo detalles ({reservation_id}): {e2}")
                return ""
        except Exception as e:
            logger.error(f"Excepción obteniendo detalles ({reservation_id}): {e}")
            return ""


    @log_execution
    def perform_action(self, method: str, url: str, **kwargs) -> bool:
        """
        Método genérico para ejecutar acciones en OtelMS.
        
        Args:
            method: 'POST' o 'GET'
            url: URL parcial o completa del endpoint
            **kwargs: Argumentos para requests (data, json, params, etc.)
        """
        if not url.startswith("http"):
            url = f"{self.BASE_URL}{url}" if url.startswith("/") else f"{self.BASE_URL}/{url}"
            
        logger.info(f"Ejecutando acción {method} en: {url}")
        
        try:
            resp = self.session.request(method, url, timeout=30, **kwargs)
            
            if config.DEBUG and config.DEBUG_REQUESTS:
                self._debug(f"Action {method}", resp)
                
            if resp.status_code == 200:
                # A veces el éxito se indica con un redirect o un JSON específico.
                # Aquí asumimos 200 OK como éxito básico.
                # Se podría analizar resp.text en busca de errores específicos "Success": false
                logger.info("Acción ejecutada correctamente (Status 200).")
                return True
            else:
                logger.warning(f"La acción falló con status {resp.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión ejecutando acción: {e}")
            return False


    def set_room_checkin(self, reservation_id: str) -> bool:
        """
        Realiza el Check-in de una reserva.
        Endpoint: /reservation_c2/set_checkin/{id}/status
        """
        endpoint = f"/reservation_c2/set_checkin/{reservation_id}/status"
        logger.info(f"Intentando Check-in para reserva {reservation_id}...")
        return self.perform_action("POST", endpoint)

    def set_room_checkout(self, reservation_id: str) -> bool:
        """
        Realiza el Checkout de una reserva.
        Endpoint: /reservation_c2/set_checkout/{id}/status
        """
        endpoint = f"/reservation_c2/set_checkout/{reservation_id}/status"
        logger.info(f"Intentando Checkout para reserva {reservation_id}...")
        return self.perform_action("POST", endpoint)

    # Alias para compatibilidad hacia atrás si es necesario, o mantener consistencia
    perform_checkout = set_room_checkout

    def update_room_availability(self, action: str, params: dict) -> bool:
        """
        Abre o cierra fechas para una habitación.
        
        Args:
            action: "open" o "close"
            params: Diccionario con los parámetros requeridos (ej. {'room_id': '...', 'dates': [...]})
        """
        if action == "open":
            endpoint = "/reservation_c2/days_open_save"
        elif action == "close":
            endpoint = "/reservation_c2/days_close_save"
        else:
            logger.error(f"Acción de disponibilidad desconocida: {action}")
            return False
        
        # Log del intento
        room_id = params.get('room_id', 'Unknown')
        dates = params.get('dates', [])
        logger.info(f"Actualizando disponibilidad ({action.upper()}) para habitación {room_id} en fechas {dates}")
        
        return self.perform_action("POST", endpoint, data=params)

    def _debug(self, context: str, response: requests.Response):
        """Imprime información útil para depurar."""
        if config.DEBUG and config.DEBUG_REQUESTS:
            print("-" * 100)
            print(f"\n=== {context} ===")
            print("URL:", response.url)
            print("Status:", response.status_code)
            print("History:", [r.status_code for r in response.history])
            print("Cookies actuales:", self.session.cookies.get_dict())
            print("-" * 100)

