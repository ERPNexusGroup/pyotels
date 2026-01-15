# src/pyotels/scarper.py
from typing import List
from typing import Optional

import diskcache as dc
import requests
from playwright.sync_api import Browser, Page, sync_playwright, TimeoutError as PlaywrightTimeoutError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .extractor import OtelsExtractor
from .logger import logger, log_execution
from .settings import config
from .utils.cache import get_cache_key
from .utils.dev import save_html_debug


class OtelMSScraper:
    """
    Scraper para OtelMS (https://{ID-Hotel}.otelms.com)
    Maneja sesión, cookies y acceso autenticado.
    Incorpora Playwright para manejar interacciones dinámicas (JS).
    """

    BASE_URL: str = ...
    LOGIN_URL: str = ...
    CALENDAR_URL: str = ...
    DETAILS_URL: str = ...

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

        # TODO: Implementacion a futuro (No eliminar)
        href = "/reservation_c2/set_checkin/22745/status"

        # TODO: antes de llegar al checkout esta de actualizar el estatus de las fechas a la primera pantalla (No Eliminar)
        href = "/reservation_c2/set_checkout/22745/status"

        # TODO: Para abrir y cerrar fechas y habitaciones (No Eliminar)
        onclick = "close_save(&quot;/reservation_c2/days_close_save&quot;)"
        onclick = "open_save(&quot;/reservation_c2/days_open_save&quot;)"

        # sesión persistente (mantiene cookies y headers)
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

        # Inicialización de Playwright (lazy)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._playwright_context_initialized = False

        # Caché
        self._cache_enabled = config.DEBUG  # o una nueva variable de entorno/cache
        self._cache_duration = 60 * 60  # 60 minutos en segundos
        if self._cache_enabled:
            cache_dir = config.BASE_DIR / "cache"
            cache_dir.mkdir(exist_ok=True)
            self.cache = dc.Cache(str(cache_dir), timeout=self._cache_duration)
            logger.info(f"Cache de HTML habilitada en: {cache_dir}")
        else:
            self.cache = None
            logger.info("Cache de HTML deshabilitada.")

        self.day_id_to_date_map = {}

    def _ensure_playwright_context(self):
        """Inicializa Playwright y comparte la sesión de cookies si es necesario."""
        if self._playwright_context_initialized:
            return

        logger.info("Inicializando contexto de Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.browser or self.playwright.chromium.launch(headless=not config.DEBUG)
        self.page = self.page or self.browser.new_page()

        # Opcional: Sincronizar cookies de la sesión de requests si es relevante
        req_cookies = self.session.cookies.get_dict()
        pw_cookies = [{"name": k, "value": v, "domain": self.BASE_URL.split('/')[-1], "path": "/"} for k, v in
                      req_cookies.items()]
        self.page.context.add_cookies(pw_cookies)

        self._playwright_context_initialized = True
        logger.info("Contexto de Playwright inicializado.")

    @log_execution
    def login(self) -> bool:
        """Intenta hacer login en OtelMS."""
        logger.info(f"Iniciando login para {self.username} en {self.id_hotel}")
        payload = {
            "login": self.username,
            "password": self.password,
            "action": "login"
        }

        try:
            resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
            if resp.status_code == 200:
                logger.info("✅ Login exitoso con requests.")
                try:
                    self._ensure_playwright_context()
                    req_cookies = self.session.cookies.get_dict(domain=f"{self.id_hotel}.{self.domain}")
                    pw_cookies = []
                    for k, v in req_cookies.items():
                        pw_domain = f".{self.id_hotel}.{self.domain}"
                        if not k.startswith('.'): pw_domain = pw_domain.lstrip('.')
                        pw_cookies.append({"name": k, "value": v, "domain": pw_domain, "path": "/", "sameSite": "Lax"})
                    self.page.context.add_cookies(pw_cookies)
                    logger.debug("Cookies compartidas con Playwright.")
                except Exception as e:
                    logger.warning(f"⚠️ No se pudieron compartir cookies con Playwright: {e}")
                return True
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión durante login: {e}")
            return False

    @log_execution
    def get_reservation_calendar(self, force_refresh: bool = False) -> str:
        """Obtiene el HTML del calendario autenticado, usando caché si está habilitada."""
        cache_key = get_cache_key(self.CALENDAR_URL)
        # Guardar en disco si es debug
        # (Nota: esto lo hacemos al final tras obtener el HTML real)

        if self._cache_enabled and not force_refresh:
            cached_html = self.cache.get(cache_key)
            if cached_html:
                logger.info("✅ Calendario obtenido desde caché.")
                if not self.day_id_to_date_map:
                    extractor = OtelsExtractor(cached_html)
                    extractor._build_date_mapping()
                    self.day_id_to_date_map = extractor.day_id_to_date
                return cached_html

        logger.info(f"Obteniendo calendario desde servidor: {self.CALENDAR_URL}")
        try:
            response = self.session.get(self.CALENDAR_URL, allow_redirects=True, timeout=30)
            if response.status_code != 200:
                logger.error(f"❌ Error obteniendo calendario. Status: {response.status_code}")
                raise RuntimeError(f"No se pudo obtener el calendario. Status: {response.status_code}")
            html_content = response.text

            # Guardar en caché y disco local
            if self._cache_enabled:
                self.cache.set(cache_key, html_content, expire=self._cache_duration)
                logger.info("💾 Calendario guardado en caché.")

            save_html_debug(html_content, f"calendar_{config.TARGET_DATE}.html")

            # Extraer y guardar el mapeo de fechas
            extractor = OtelsExtractor(html_content)
            extractor._build_date_mapping()
            self.day_id_to_date_map = extractor.day_id_to_date

            return html_content
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de conexión obteniendo calendario: {e}")
            raise

    @log_execution
    def navigate_calendar(self, shift_days: int = 0, shift_months: int = 0):
        """
        Navega el calendario hacia adelante o atrás.
        :param shift_days: Número de días para avanzar (+) o retroceder (-).
                           No se usa si shift_months != 0.
        :param shift_months: Número de meses para avanzar (+) o retroceder (-).
        """
        if shift_months != 0:
            logger.info(f"Navegando calendario {shift_months} meses...")
            self._ensure_playwright_context()
            self.page.goto(self.CALENDAR_URL)
            try:
                # Esperar a que el calendario esté cargado
                self.page.wait_for_selector('div.calendar_month', state='visible', timeout=10000)
                # Click en flecha derecha/incrementar mes si shift_months > 0, izquierda si < 0
                for _ in range(abs(shift_months)):
                    if shift_months > 0:
                        self.page.click('input[value="+7"]')
                    else:
                        self.page.click('input[value="-7"]')
                    # Esperar a que se cargue el nuevo mes
                    self.page.wait_for_load_state('networkidle', timeout=15000)
            except PlaywrightTimeoutError:
                logger.error("❌ Timeout esperando carga del calendario después de navegar.")
                raise
            except Exception as e:
                logger.error(f"❌ Error navegando calendario: {e}")
                raise
        else:
            # Navegación por días (si aplica, aunque el HTML no muestra botones obvios para días sueltos)
            # Se puede usar el datein100 input si es necesario
            logger.info(
                "Navegación por días no implementada directamente con botones. Se puede usar datein100 si es necesario.")
            pass  # Implementar si se requiere

    @log_execution
    def get_calendar_html_playwright(self, force_refresh: bool = False) -> str:
        """
        Obtiene el HTML *después* de que Playwright haya manipulado el DOM.
        Útil para obtener el calendario tras navegarlo.
        """
        self._ensure_playwright_context()
        # Asegurarse de estar en la página correcta
        if self.page.url != self.CALENDAR_URL:
            logger.info(f"Navegando a calendario con Playwright: {self.CALENDAR_URL}")
            self.page.goto(self.CALENDAR_URL)
            self.page.wait_for_load_state('networkidle', timeout=15000)

        cache_key = get_cache_key(self.CALENDAR_URL, params={"via": "playwright"})
        if self._cache_enabled and not force_refresh:
            cached_html = self.cache.get(cache_key)
            if cached_html:
                logger.info("✅ HTML de calendario (post-Playwright) obtenido desde caché.")
                return cached_html

        html_content = self.page.content()
        if self._cache_enabled:
            self.cache.set(cache_key, html_content, expire=self._cache_duration)
            logger.info("💾 HTML de calendario (post-Playwright) guardado en caché.")
        return html_content

    @log_execution
    def set_room_checkin_playwright(self, reservation_id: str) -> bool:
        """
        Realiza el check-in de una reserva usando Playwright.
        """
        logger.info(f"Intentando Check-in para reserva {reservation_id} usando Playwright...")
        self._ensure_playwright_context()
        try:
            # Construir la URL del folio
            folio_url = self.DETAILS_URL % reservation_id
            self.page.goto(folio_url)
            self.page.wait_for_load_state('networkidle')

            # Buscar el botón de check-in
            # El HTML muestra: <a id="do_checkin" reservation_id="..." href="/master_c2/step_1/.../?landing_page=folio" ...>
            button_selector = f'a#do_checkin[reservation_id="{reservation_id}"]'
            checkin_button = self.page.locator(button_selector)
            if checkin_button.count() > 0:
                checkin_button.click()
                # Esperar a que se complete la acción o aparezca un mensaje
                self.page.wait_for_timeout(3000)  # Esperar procesamiento
                logger.info(f"✅ Check-in iniciado para reserva {reservation_id} con Playwright.")
                return True
            else:
                logger.warning(f"⚠️ Botón de check-in no encontrado para reserva {reservation_id}")
                return False
        except Exception as e:
            logger.error(f"❌ Error en check-in Playwright para reserva {reservation_id}: {e}")
            return False

    @log_execution
    def set_room_checkout_playwright(self, reservation_id: str) -> bool:
        """
        Realiza el checkout de una reserva usando Playwright.
        """
        logger.info(f"Intentando Checkout para reserva {reservation_id} usando Playwright...")
        self._ensure_playwright_context()
        try:
            folio_url = self.DETAILS_URL % reservation_id
            self.page.goto(folio_url)
            self.page.wait_for_load_state('networkidle')

            # Buscar el botón de checkout
            # El HTML muestra: <a id="do_checkout" reservation_id="..." href="/master_c2/checkout_step_1/...?landing_page=folio" ...>
            button_selector = f'a#do_checkout[reservation_id="{reservation_id}"]'
            checkout_button = self.page.locator(button_selector)
            if checkout_button.count() > 0:
                checkout_button.click()
                self.page.wait_for_timeout(3000)  # Esperar procesamiento
                logger.info(f"✅ Checkout iniciado para reserva {reservation_id} con Playwright.")
                return True
            else:
                logger.warning(f"⚠️ Botón de checkout no encontrado para reserva {reservation_id}")
                return False
        except Exception as e:
            logger.error(f"❌ Error en checkout Playwright para reserva {reservation_id}: {e}")
            return False

    def _map_dates_to_day_ids(self, dates: List[str]) -> List[str]:
        """
        Mapea una lista de fechas (YYYY-MM-DD) a sus correspondientes day_ids.
        Requiere que self.day_id_to_date_map esté poblado.
        """
        if not self.day_id_to_date_map:
            logger.warning("⚠️ Mapa de fechas vacío. Intentando poblarlo obteniendo el calendario.")
            self.get_reservation_calendar()

        day_ids = []
        # Invertir el mapa para búsqueda rápida: date -> day_id
        date_to_day_id = {v: k for k, v in self.day_id_to_date_map.items()}

        for date in dates:
            day_id = date_to_day_id.get(date)
            if day_id:
                day_ids.append(day_id)
            else:
                logger.warning(f"⚠️ No se encontró day_id para la fecha {date}")

        # Ordenar day_ids numéricamente si es posible, o mantener orden de fechas
        # Asumiendo que day_ids son numéricos o secuenciales
        return day_ids

    @log_execution
    def update_room_availability_playwright(self, room_id: str, dates: List[str], action: str) -> bool:
        """
        Abre o cierra fechas de una habitación usando Playwright.
        :param room_id: ID de la habitación.
        :param dates: Lista de fechas en formato 'YYYY-MM-DD'.
        :param action: 'open' o 'close'.
        """
        if action not in ['open', 'close']:
            logger.error(f"❌ Acción de disponibilidad inválida: {action}")
            return False

        logger.info(f"Intentando {action} fechas para habitación {room_id} en fechas {dates} usando Playwright...")
        self._ensure_playwright_context()
        try:
            # Navegar al calendario
            self.page.goto(self.CALENDAR_URL)
            self.page.wait_for_load_state('networkidle')

            # Obtener day_ids correspondientes a las fechas
            day_ids = self._map_dates_to_day_ids(dates)
            if not day_ids:
                logger.error("❌ No se encontraron day_ids para las fechas proporcionadas.")
                return False

            # Ordenar day_ids para asegurar selección correcta (asumiendo que son strings numéricos)
            try:
                day_ids.sort(key=int)
            except ValueError:
                day_ids.sort()  # Fallback a orden lexicográfico

            logger.info(f"Seleccionando {len(day_ids)} celdas en el calendario...")

            # Estrategia de selección: Click en primero, Shift+Click en último para rango
            # Esto asume que las fechas son contiguas. Si no, se debería usar Ctrl+Click individualmente.
            # Vamos a asumir rango contiguo para simplificar, o iterar con Ctrl si no.
            # Para mayor robustez, usaremos Ctrl+Click (o Meta en Mac) para cada celda individualmente
            # o Shift si detectamos que es un rango continuo.

            # Implementación robusta: Click en cada celda con modificador Control/Meta
            # Nota: Playwright maneja modifiers en click.

            modifier = 'Control'  # O 'Meta' en macOS

            # Primer click sin modificador para limpiar selecciones previas y enfocar
            first_day_id = day_ids[0]
            first_cell_selector = f'td[day_id="{first_day_id}"][room_id="{room_id}"]'

            try:
                self.page.click(first_cell_selector)
            except PlaywrightTimeoutError:
                logger.error(f"❌ No se pudo encontrar la celda inicial: {first_cell_selector}")
                return False

            # Clicks restantes con modificador
            if len(day_ids) > 1:
                # Si son muchas fechas, puede ser lento. Si es un rango continuo, Shift+Click es mejor.
                # Verificamos si es rango continuo simple (opcional, por ahora iteramos)

                # Opción optimizada: Si son más de 2 y parecen consecutivos, usar Shift en el último
                # Pero para seguridad, iteramos con Control.
                for day_id in day_ids[1:]:
                    cell_selector = f'td[day_id="{day_id}"][room_id="{room_id}"]'
                    try:
                        self.page.click(cell_selector, modifiers=[modifier])
                    except Exception as e:
                        logger.warning(f"⚠️ Error seleccionando celda {day_id}: {e}")

            # Esperar un momento para que la UI procese la selección
            self.page.wait_for_timeout(500)

            # 3. Realizar la acción de abrir/cerrar
            # Buscar el botón correspondiente
            action_button_selector = f'#{action}_save'

            if self.page.locator(action_button_selector).count() > 0:
                logger.info(f"Botón de '{action}' encontrado. Ejecutando acción...")
                self.page.click(action_button_selector)

                # Manejar modal de confirmación si existe
                # A veces aparece un modal donde hay que confirmar
                # Selector genérico de botón de guardar en modal: button.btn-primary o similar
                # O esperar a que desaparezca el modal o aparezca mensaje de éxito

                # Esperar posible modal y confirmarlo
                try:
                    # Ejemplo: esperar un botón de "Guardar" o "Confirmar" dentro de un modal visible
                    # Esto es especulativo, ajustar según el HTML real del modal
                    save_btn_modal = self.page.locator('div.modal.in .btn-primary, div.modal.in button[type="submit"]')
                    if save_btn_modal.count() > 0 and save_btn_modal.is_visible():
                        save_btn_modal.click()
                        logger.info("Confirmación en modal realizada.")
                except Exception:
                    pass  # Si no hay modal o falla, continuamos

                # Esperar a que se complete la acción (recarga o mensaje)
                self.page.wait_for_load_state('networkidle')
                logger.info(f"✅ Acción {action} completada (simulada/ejecutada).")
                return True
            else:
                logger.warning(f"⚠️ Botón de '{action}' no encontrado después de selección de fechas.")
                return False

        except Exception as e:
            logger.error(f"❌ Error en actualización de disponibilidad Playwright para habitación {room_id}: {e}")
            return False

    # --- FIN NUEVAS FUNCIONES CON PLAYWRIGHT ---

    @log_execution
    def get_reservation_details(self, reservation_id: str, force_refresh: bool = False) -> str:
        """Obtiene el HTML de la página de detalles de una reserva, usando caché si está habilitada."""
        url = self.DETAILS_URL % reservation_id
        cache_key = get_cache_key(url)

        if self._cache_enabled and not force_refresh:
            cached_html = self.cache.get(cache_key)
            if cached_html:
                logger.info(f"✅ Detalles de reserva {reservation_id} obtenidos desde caché.")
                return cached_html

        logger.info(f"Obteniendo detalles de reserva desde servidor: {reservation_id}")
        try:
            resp = self.session.get(url, allow_redirects=True, timeout=30)
            if resp.status_code != 200:
                logger.error(f"❌ Error obteniendo detalles ({reservation_id}): {resp.status_code}")
                return ""
            html_content = resp.text
            if self._cache_enabled:
                self.cache.set(cache_key, html_content, expire=self._cache_duration)
                logger.info(f"💾 Detalles de reserva {reservation_id} guardados en caché.")

            save_html_debug(html_content, f"reservation_{reservation_id}.html")

            return html_content
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo detalles ({reservation_id}): {e}")
            return ""

    def close(self):
        """Cierra recursos de Playwright si están abiertos."""
        if self.page:
            self.page.close()
            self.page = None
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
        self._playwright_context_initialized = False
        logger.info("Recursos de Playwright cerrados.")

    get_calendar_html = get_reservation_calendar
