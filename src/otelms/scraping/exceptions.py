"""
Excepciones específicas del scraping.
"""


class ScrapingError(Exception):
    """Base exception for scraping errors."""
    def __init__(self, message: str, hotel_id: str | None = None, url: str | None = None):
        self.hotel_id = hotel_id
        self.url = url
        super().__init__(message)


class AuthenticationError(ScrapingError):
    """Error de autenticación (credenciales inválidas, sesión expirada)."""
    pass


class NavigationError(ScrapingError):
    """Error de navegación (página no carga, timeout, redirect inesperado)."""
    pass


class ExtractionError(ScrapingError):
    """Error extrayendo datos (selectores no encontrados, parsing fallido)."""
    pass


class RateLimitError(ScrapingError):
    """Rate limit excedido."""
    def __init__(self, message: str, retry_after: int | None = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class BrowserError(ScrapingError):
    """Error del navegador (Playwright/Camoufox crash, contexto perdido)."""
    pass


class SessionExpiredError(AuthenticationError):
    """Sesión expirada - requiere re-login."""
    pass


class ElementNotFoundError(ExtractionError):
    """Elemento esperado no encontrado en la página."""
    def __init__(self, selector: str, **kwargs):
        self.selector = selector
        msg = f"Element not found: {selector}"
        super().__init__(msg, **kwargs)


class ParsingError(ExtractionError):
    """Error parseando datos extraídos."""
    def __init__(self, field: str, raw_value: str, **kwargs):
        self.field = field
        self.raw_value = raw_value
        msg = f"Failed to parse {field}: {raw_value}"
        super().__init__(msg, **kwargs)
