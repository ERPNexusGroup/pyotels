# src/pyotels/extractor.py
import time
from typing import Optional, List, Dict

import diskcache as dc
import requests
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyotels.utils.logger import get_logger
from pyotels.config.settings import config
from pyotels.exceptions import NetworkError, AuthenticationError
from pyotels.utils.cache import get_cache_key


class OtelsExtractor:
    """
    Extractor de HTML usando Playwright.
    Maneja la sesión, autenticación y navegación.
    """

    def __init__(self, base_url: str, username: Optional[str], password: Optional[str], headless: bool = True,
                 use_cache: bool = False):
        self.logger = get_logger(classname='OtelsExtractor')

        self.username = username
        self.password = password

        self.headless = headless
        self.base_url = base_url
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.LOGIN_URL = f"{self.base_url}/login/DoLogIn/"
        self.CALENDAR_URL = f"{self.base_url}/reservation_c2/calendar"
        self.DETAILS_URL = f"{self.base_url}/reservation_c2/folio/%s/1"
        self.GUEST_DETAILS_URL = f"{self.base_url}/reservation_c2/guestfolio/%s"

        # Configuración de caché
        # La caché se habilita si config.DEBUG es True Y use_cache es True
        self._cache_enabled = config.DEBUG and use_cache
        self._cache_duration = 60 * 60

        if self._cache_enabled:
            cache_dir = config.BASE_DIR / "cache"
            cache_dir.mkdir(exist_ok=True)
            self.cache = dc.Cache(str(cache_dir), timeout=self._cache_duration)
            self.logger.info(f"Cache de HTML habilitada en: {cache_dir}")
        else:
            self.cache = None
            self.logger.info("Cache de HTML deshabilitada.")

        # Sesión de requests para login inicial (estrategia híbrida)
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": config.ACCEPT_REQUEST,
            "Connection": "keep-alive"
        })

    def start(self):
        """Inicializa los recursos de Playwright si no están activos."""
        if self.playwright: return

        self.logger.info("Iniciando Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)

        # Crear contexto con User-Agent definido
        self.context = self.browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = self.context.new_page()

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Realiza el login en el sistema.
        Utiliza requests para la autenticación POST y transfiere cookies a Playwright.
        """
        self.start()
        self.logger.info(f"Iniciando login para {username if username else self.username} en {self.base_url}")

        payload = {"login": username if username else self.username,
                   "password": password if password else self.password, "action": "login"}

        try:
            # Actualizar headers para el login
            self.session.headers.update({
                "Referer": self.LOGIN_URL,
                "Origin": self.base_url
            })

            resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
            resp.raise_for_status()

            # Verificar éxito del login
            if "login" not in resp.url:
                self.logger.info("✅ Login exitoso (Requests). Sincronizando cookies...")
                self._sync_cookies()
                return True

            # Buscar errores explícitos
            error_keywords = ["incorrect", "error", "failed", "invalid"]
            lower_text = resp.text.lower()
            if any(k in lower_text for k in error_keywords):
                raise AuthenticationError("Credenciales incorrectas o error en login.")

            self.logger.warning("⚠️ URL sigue siendo login, intentando sincronizar cookies de todos modos...")
            self._sync_cookies()

            # Verificación opcional: Navegar a una página protegida para confirmar
            # Por ahora asumimos True si no hubo error explícito
            return True

        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Error de conexión durante login: {e}")

    def _sync_cookies(self):
        """Transfiere las cookies de la sesión de requests al contexto de Playwright."""
        if not self.context: return

        req_cookies = self.session.cookies.get_dict()
        if req_cookies:
            domain = self.base_url.split('//')[-1].split('/')[0]
            pw_cookies = []
            for k, v in req_cookies.items():
                pw_cookies.append({
                    "name": k,
                    "value": v,
                    "domain": domain,
                    "path": "/"
                })
            self.context.add_cookies(pw_cookies)
            self.logger.debug(f"Cookies sincronizadas: {len(pw_cookies)}")

    def get_calendar_html(self, target_date_str: str = None) -> str:
        """
        Navega a la URL del calendario y extrae el HTML completo.
        """
        params = {}

        if target_date_str: params['date'] = target_date_str
        # 1. Caché
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            # Nota: Usamos la URL del extractor para generar la key de caché
            # para mantener consistencia, aunque la URL es interna del extractor ahora.
            cache_key = get_cache_key(self.CALENDAR_URL, params)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Navegando al calendario: {self.CALENDAR_URL} (fecha: {target_date_str})")

        full_url = self.CALENDAR_URL
        if target_date_str:
            separator = '&' if '?' in self.CALENDAR_URL else '?'
            full_url = f"{self.CALENDAR_URL}{separator}date={target_date_str}"

        try:
            self.page.goto(full_url, wait_until="domcontentloaded", timeout=60000)

            # Validación de sesión en la página cargada
            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado (redirigido a login).")

            try:
                self.page.wait_for_selector("table.calendar_table", timeout=config.WAIT_FOR_SELECTOR)
            except PlaywrightTimeoutError:
                self.logger.warning("Timeout esperando tabla del calendario, intentando continuar con el HTML actual.")

            time.sleep(1)  # Pequeña espera para scripts dinámicos

            html_content = self.page.content()

            # 3. Guardar en caché y debug
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content
        except PlaywrightTimeoutError:
            raise NetworkError("Timeout al cargar el calendario con Playwright.")
        except PlaywrightError as e:
            raise NetworkError(f"Error de Playwright al obtener calendario: {e}")
        except AuthenticationError:
            raise

    def get_reservation_detail_html(self, reservation_id: str) -> str:
        """
        Navega a la URL de detalle de reserva y extrae el HTML.
        """
        url = self.DETAILS_URL % reservation_id

        # 1. Verificar caché antes de navegar
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            cache_key = get_cache_key(url)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Navegando a detalle de reserva: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=config.WAIT_FOR_SELECTOR)

            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado.")

            try:
                self.page.wait_for_selector("div.panel", timeout=config.WAIT_FOR_SELECTOR)
            except PlaywrightTimeoutError:
                pass

            html_content = self.page.content()

            # 2. Guardar en caché
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content
        except PlaywrightTimeoutError:
            raise NetworkError(f"Timeout al cargar detalle de reserva {reservation_id}")
        except PlaywrightError as e:
            raise NetworkError(f"Error de Playwright al obtener detalle: {e}")
        except AuthenticationError:
            raise

    def get_reservation_accommodation_detail_html(self, reservation_id: str) -> str:
        """
        Navega al detalle de la reserva, hace clic en el botón 'Editar' (#edit_reservation)
        y extrae el HTML del modal cargado con la información de alojamiento.
        """
        url = self.DETAILS_URL % reservation_id

        # 1. Verificar caché (usamos un sufijo para diferenciar del detalle normal)
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            cache_key = get_cache_key(url + "#accommodation_modal")
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML de modal alojamiento recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Obteniendo modal de edición de alojamiento para: {reservation_id}")

        try:
            # Navegar a la página de detalle
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado.")

            # Esperar y hacer clic en el botón Editar
            edit_btn_selector = "#edit_reservation"
            try:
                self.page.wait_for_selector(edit_btn_selector, state="visible", timeout=config.WAIT_FOR_SELECTOR)
                self.page.click(edit_btn_selector)
            except PlaywrightTimeoutError:
                raise NetworkError(f"No se encontró el botón 'Editar' para la reserva {reservation_id}")

            # Esperar a que el modal y el formulario interno carguen
            # Usamos :has() para seleccionar el modal específico que contiene el formulario cargado
            # Esto evita seleccionar el modal incorrecto (hay múltiples .modal-dialog en el DOM)
            modal_selector = "div.modal-dialog:has(#modalform)"

            self.page.wait_for_selector(modal_selector, state="visible", timeout=config.WAIT_FOR_SELECTOR)

            time.sleep(0.5)  # Pequeña espera para renderizado final

            # Extraer HTML del modal completo
            modal_element = self.page.query_selector(modal_selector)
            if not modal_element:
                raise NetworkError("El modal se abrió pero no se pudo seleccionar en el DOM.")

            html_content = modal_element.evaluate("el => el.outerHTML")

            # Cerrar modal para limpiar estado visual
            self.page.keyboard.press("Escape")

            # 2. Guardar en caché
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content

        except AuthenticationError:
            raise
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            self.logger.error(f"Error interactuando con modal de alojamiento {reservation_id}: {e}")
            # Intentar cerrar modal por si acaso quedó abierto tras error
            try:
                self.page.keyboard.press("Escape")
            except:
                pass
            raise NetworkError(f"Error al obtener modal de alojamiento: {e}")

    def get_guest_detail_html(self, guest_id: str) -> str:
        """
        Navega a la URL de detalle del huésped y extrae el HTML.
        """
        url = self.GUEST_DETAILS_URL % guest_id

        # 1. Verificar caché antes de navegar
        cache_key = None
        if self._cache_enabled and self.cache is not None:
            cache_key = get_cache_key(url)
            cached_html = self.cache.get(cache_key)
            if cached_html:
                self.logger.info(f"✅ HTML de huésped recuperado de caché (key={cache_key[:8]}...)")
                return cached_html

        self.start()
        self.logger.info(f"Navegando a detalle de huésped: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)

            if "login" in self.page.url:
                raise AuthenticationError("La sesión ha expirado.")

            try:
                self.page.wait_for_selector("div.panel", timeout=config.WAIT_FOR_SELECTOR)
            except PlaywrightTimeoutError:
                pass

            html_content = self.page.content()

            # 2. Guardar en caché
            if self._cache_enabled and self.cache is not None and cache_key:
                self.cache.set(cache_key, html_content)

            return html_content
        except PlaywrightError as e:
            raise NetworkError(f"Error al obtener HTML de detalle de huésped: {e}")
        except AuthenticationError:
            raise

    def get_multiple_reservation_details_html(self, reservation_ids: List[str]) -> Dict[str, str]:
        """
        Itera sobre una lista de IDs y obtiene el HTML de detalle para cada uno.
        Retorna un diccionario {reservation_id: html}.
        """
        results = {}
        self.logger.info(f"Iniciando extracción masiva de detalles para {len(reservation_ids)} reservas...")

        for i, res_id in enumerate(reservation_ids):
            try:
                self.logger.debug(f"Procesando reserva {i + 1}/{len(reservation_ids)}: {res_id}")
                html = self.get_reservation_detail_html(res_id)
                results[res_id] = html
            except NetworkError as e:
                self.logger.error(f"Error obteniendo detalle para reserva {res_id}: {e}")
                # No interrumpimos todo el proceso, pero logueamos el error.
                continue
            except AuthenticationError:
                raise

        self.logger.info(f"Extracción masiva completada. {len(results)} detalles obtenidos.")
        return results

    def get_visible_reservation_ids(self,target_date_str: str = None) -> List[str]:
        """
        Escanea la página actual del calendario y retorna una lista de todos los IDs de reserva visibles.
        """
        self.start()
        # Asegurar que estamos en el calendario
        if not self.page.url.startswith(self.CALENDAR_URL):
            self.get_calendar_html(target_date_str)

        try:
            # Seleccionar todos los elementos que tengan el atributo 'resid'
            # Usamos JS eval para obtener los atributos rápidamente
            ids = self.page.evaluate("""() => {
                const elements = document.querySelectorAll('div.calendar_item[resid]');
                return Array.from(elements).map(el => el.getAttribute('resid')).filter(id => id);
            }""")

            # Eliminar duplicados
            unique_ids = list(set(ids))
            self.logger.info(f"Encontrados {len(unique_ids)} IDs de reserva visibles en el calendario.")
            return unique_ids
        except PlaywrightError as e:
            self.logger.error(f"Error obteniendo IDs de reservas: {e}")
            raise NetworkError(f"Error al obtener IDs de reservas: {e}")

    def get_reservation_modal_html(self, reservation_id: str) -> str:
        """
        Navega al calendario (si no está ya ahí), busca la reserva por ID,
        hace clic para abrir el modal y extrae el HTML del modal.
        """
        self.start()
        self.logger.info(f"Intentando abrir modal para reserva ID: {reservation_id}")

        # Asegurar que estamos en el calendario
        if not self.page.url.startswith(self.CALENDAR_URL):
            self.logger.info("No estamos en el calendario, navegando...")
            self.get_calendar_html()

        try:
            # Selector para el bloque de reserva
            res_selector = f"div[resid='{reservation_id}']"

            # Esperar a que la reserva sea visible
            try:
                self.page.wait_for_selector(res_selector, state="visible", timeout=config.WAIT_FOR_SELECTOR)
            except PlaywrightTimeoutError:
                self.logger.warning(f"Reserva {reservation_id} no encontrada visible en la vista actual.")
                raise NetworkError(f"Reserva {reservation_id} no encontrada en el calendario actual.")

            # Hacer clic en la reserva
            # force=True ayuda si el elemento está parcialmente cubierto
            self.page.click(res_selector, force=True)

            # Esperar a que aparezca el modal
            modal_selector = "div.modal-content"
            self.page.wait_for_selector(modal_selector, state="visible", timeout=config.WAIT_FOR_SELECTOR)

            time.sleep(0.5)  # Pequeña espera para renderizado

            # Extraer el HTML del modal
            modal_element = self.page.query_selector(modal_selector)
            if modal_element:
                modal_html = modal_element.inner_html()

                # Cerrar el modal para limpiar
                self.page.keyboard.press("Escape")
                # Esperar a que el modal desaparezca para no interferir con el siguiente clic
                try:
                    self.page.wait_for_selector(modal_selector, state="hidden", timeout=config.WAIT_FOR_SELECTOR)
                except:
                    pass  # Si no desaparece rápido, seguimos igual

                return modal_html
            else:
                raise NetworkError("El modal se abrió pero no se pudo obtener su contenido.")

        except AuthenticationError:
            raise
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            self.logger.error(f"Error interactuando con el modal de reserva {reservation_id}: {e}")
            # Intentar cerrar modal por si acaso quedó abierto tras error
            try:
                self.page.keyboard.press("Escape")
            except:
                pass
            raise NetworkError(f"Error obteniendo modal de reserva: {e}")

    def collect_all_reservation_modals(self) -> Dict[str, str]:
        """
        Itera sobre todas las reservas visibles en el calendario actual,
        abre sus modales y recolecta el HTML de cada uno.
        Retorna un diccionario {reservation_id: html_modal}.
        """
        results = {}
        ids = self.get_visible_reservation_ids()

        self.logger.info(f"Iniciando extracción masiva de modales para {len(ids)} reservas...")

        for i, res_id in enumerate(ids):
            try:
                self.logger.debug(f"Procesando reserva {i + 1}/{len(ids)}: {res_id}")
                html = self.get_reservation_modal_html(res_id)
                results[res_id] = html
                # Pequeña pausa para no saturar la UI del navegador
                time.sleep(0.2)
            except NetworkError as e:
                self.logger.error(f"Saltando reserva {res_id} debido a error: {e}")
                continue
            except AuthenticationError:
                raise

        self.logger.info(f"Extracción masiva completada. {len(results)} modales obtenidos.")
        return results

    def close(self):
        """Cierra todos los recursos."""
        if self.page: self.page.close()
        if self.context: self.context.close()
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        self.session.close()

        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        self.logger.info("Recursos de Extractor cerrados.")
