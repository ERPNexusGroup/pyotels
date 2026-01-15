# src/pyotels/extractor.py
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .logger import logger
from .exceptions import NetworkError

class OtelsExtractor:
    """
    Extractor de HTML usando Playwright.
    Se encarga únicamente de obtener el HTML crudo de las páginas.
    """

    def __init__(self, page: Page):
        self.page = page

    def get_calendar_html(self, url: str, target_date_str: str = None) -> str:
        """
        Navega a la URL del calendario y extrae el HTML completo.
        """
        logger.info(f"Navegando al calendario: {url} (fecha: {target_date_str})")
        
        full_url = url
        if target_date_str:
            if '?' in url:
                full_url = f"{url}&date={target_date_str}"
            else:
                full_url = f"{url}?date={target_date_str}"

        try:
            self.page.goto(full_url, wait_until="domcontentloaded", timeout=60000)
            
            # Esperar a que la tabla del calendario esté visible
            # Ajustar selector según sea necesario, por ejemplo 'table.calendar_table' o similar
            try:
                self.page.wait_for_selector("table.calendar_table", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout esperando tabla del calendario, intentando continuar con el HTML actual.")

            # Pequeña espera adicional para asegurar carga dinámica
            time.sleep(2) 
            
            html_content = self.page.content()
            return html_content

        except PlaywrightTimeoutError:
            raise NetworkError("Timeout al cargar el calendario con Playwright.")
        except Exception as e:
            raise NetworkError(f"Error al obtener HTML del calendario: {e}")

    def get_reservation_detail_html(self, url: str) -> str:
        """
        Navega a la URL de detalle de reserva y extrae el HTML.
        """
        logger.info(f"Navegando a detalle de reserva: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            # Esperar algún elemento clave del detalle
            try:
                self.page.wait_for_selector("div.panel", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            html_content = self.page.content()
            return html_content
        except Exception as e:
            raise NetworkError(f"Error al obtener HTML de detalle: {e}")
