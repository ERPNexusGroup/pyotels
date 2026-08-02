"""
Autenticación y gestión de sesión para OtelMS.
Maneja login híbrido (requests + Playwright), persistencia de cookies, auto-relogin, 2FA/MFA.
"""
import asyncio
import time
from dataclasses import dataclass

import httpx
import pyotp
from playwright.async_api import BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from otelms.config.constants import OtelMSUrls, Timeouts
from otelms.config.settings import settings
from otelms.scraping.exceptions import (
    AuthenticationError,
)
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class TwoFactorHandler:
    """Base class for 2FA handlers."""

    async def get_code(self) -> str:
        """Get the 2FA code."""
        raise NotImplementedError


class TOTPHandler(TwoFactorHandler):
    """TOTP-based 2FA handler (Google Authenticator, Authy, etc.)."""

    def __init__(self, secret: str):
        self.secret = secret
        self._totp = pyotp.TOTP(secret)

    async def get_code(self) -> str:
        """Get current TOTP code."""
        return self._totp.now()

    def verify_code(self, code: str) -> bool:
        """Verify a TOTP code."""
        return self._totp.verify(code)


class SMSHandler(TwoFactorHandler):
    """SMS-based 2FA handler."""

    def __init__(self, phone_number: str):
        self.phone_number = phone_number
        self._code: str | None = None

    async def get_code(self) -> str:
        """Get SMS code - placeholder for actual implementation."""
        # In production, this would integrate with SMS API (Twilio, etc.)
        # or wait for user input
        if self._code:
            return self._code
        raise NotImplementedError("SMS 2FA requires external integration")

    def set_code(self, code: str) -> None:
        """Set the received SMS code."""
        self._code = code


class EmailHandler(TwoFactorHandler):
    """Email-based 2FA handler."""

    def __init__(self, email: str):
        self.email = email
        self._code: str | None = None

    async def get_code(self) -> str:
        """Get email code - placeholder for actual implementation."""
        # In production, this would integrate with email API or wait for user input
        if self._code:
            return self._code
        raise NotImplementedError("Email 2FA requires external integration")

    def set_code(self, code: str) -> None:
        """Set the received email code."""
        self._code = code


@dataclass
class SessionData:
    """Datos de sesión persistibles."""
    cookies: list[dict]
    user_agent: str
    hotel_id: str
    username: str
    created_at: float
    expires_at: float | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class OtelMSAuth:
    """
    Gestor de autenticación para OtelMS.
    - Login híbrido: requests para POST + Playwright para sesión
    - Persistencia de cookies en cache/DB
    - Auto-detección de sesión expirada
    - Re-login automático
    - Soporte 2FA/MFA (TOTP, SMS, Email)
    """

    def __init__(
        self,
        hotel_id: str,
        username: str,
        password: str,
        base_domain: str = "otelms.com",
        two_factor_handler: TwoFactorHandler | None = None,
    ):
        self.hotel_id = hotel_id
        self.username = username
        self.password = password
        self.base_domain = base_domain
        self.urls = OtelMSUrls(base_domain, hotel_id)
        self.two_factor_handler = two_factor_handler

        self._session_data: SessionData | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._login_lock = asyncio.Lock()

    @property
    def login_url(self) -> str:
        return self.urls.login_url

    async def initialize_http_client(self) -> None:
        """Inicializa cliente HTTP para login inicial."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
                headers={
                    "User-Agent": settings.browser_user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                    "Connection": "keep-alive",
                },
            )

    async def close_http_client(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def login(self, context: BrowserContext, force: bool = False) -> bool:
        """
        Realiza login en OtelMS.
        Usa requests para el POST y sincroniza cookies con Playwright.
        """
        async with self._login_lock:
            # Verificar si ya tenemos sesión válida
            if not force and self._session_data and not self._session_data.is_expired():
                logger.debug("Using cached session")
                await self._restore_session(context)
                if await self._verify_session(context):
                    return True

            logger.info("Performing fresh login", hotel_id=self.hotel_id)
            return await self._perform_login(context)

    async def _perform_login(self, context: BrowserContext) -> bool:
        """Ejecuta el login real."""
        await self.initialize_http_client()

        try:
            # 1. GET login page para obtener cookies iniciales y CSRF si existe
            await self._http_client.get(self.login_url)

            # 2. POST login
            payload = {
                "login": self.username,
                "password": self.password,
                "action": "login",
            }

            headers = {
                "Referer": self.login_url,
                "Origin": self.urls.base_url,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            response = await self._http_client.post(
                self.login_url,
                data=payload,
                headers=headers,
            )

            # 3. Check for 2FA challenge
            if await self._handle_2fa_challenge(response, context):
                # 2FA was handled, continue to verification
                pass
            else:
                # 3. Verify success (no 2FA needed)
                if response.status_code >= 400:
                    raise AuthenticationError(
                        f"Login HTTP error: {response.status_code}",
                        hotel_id=self.hotel_id,
                        url=self.login_url,
                    )

                # Verify redirect (éxito = no vuelve a login)
                if "login" in str(response.url).lower():
                    # Verificar mensajes de error en HTML
                    error_keywords = ["incorrect", "error", "failed", "invalid", "inválido", "incorrecto"]
                    html_lower = response.text.lower()
                    if any(k in html_lower for k in error_keywords):
                        raise AuthenticationError(
                            "Credenciales incorrectas",
                            hotel_id=self.hotel_id,
                        )
                    # A veces redirige a login pero con cookies válidas
                    logger.warning("Login URL still in response, trying to sync cookies anyway")

            # 4. Sincronizar cookies a Playwright
            await self._sync_cookies_to_context(context)

            # 5. Verificar sesión navegando a página protegida
            if not await self._verify_session(context):
                raise AuthenticationError(
                    "Login succeeded but session verification failed",
                    hotel_id=self.hotel_id,
                )

            # 6. Guardar datos de sesión
            self._session_data = SessionData(
                cookies=self._http_client.cookies.jar._cookies,  # type: ignore
                user_agent=settings.browser_user_agent,
                hotel_id=self.hotel_id,
                username=self.username,
                created_at=time.time(),
                expires_at=time.time() + 3600,  # 1 hora
            )

            logger.info("Login successful", hotel_id=self.hotel_id)
            return True

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("Login failed", error=str(e))
            raise AuthenticationError(f"Login failed: {e}", hotel_id=self.hotel_id) from e

    async def _handle_2fa_challenge(self, response: httpx.Response, context: BrowserContext) -> bool:
        """
        Detecta y maneja desafío 2FA en la respuesta de login.
        Retorna True si se manejó 2FA, False si no se requiere 2FA.
        """
        if not self.two_factor_handler:
            return False

        # Verificar si la respuesta indica 2FA requerido
        html = response.text.lower()
        twofa_keywords = ["2fa", "two-factor", "two factor", "autenticación de dos factores",
                          "código de verificación", "verification code", "totp", "authenticator"]

        if not any(k in html for k in twofa_keywords):
            return False

        logger.info("2FA challenge detected", hotel_id=self.hotel_id)

        try:
            # Obtener código 2FA
            code = await self.two_factor_handler.get_code()
            logger.debug("2FA code obtained")

            # Enviar código 2FA - esto depende de la implementación específica de OtelMS
            # Por ahora, asumimos que hay un formulario de 2FA en la misma URL de login
            payload = {
                "login": self.username,
                "password": self.password,
                "action": "login",
                "2fa_code": code,
            }

            headers = {
                "Referer": self.login_url,
                "Origin": self.urls.base_url,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            response = await self._http_client.post(
                self.login_url,
                data=payload,
                headers=headers,
            )

            logger.info("2FA code submitted")
            return True

        except Exception as e:
            logger.error("2FA handling failed", error=str(e))
            raise AuthenticationError(f"2FA handling failed: {e}", hotel_id=self.hotel_id) from e

    async def _sync_cookies_to_context(self, context: BrowserContext) -> None:
        """Transfiere cookies de httpx a Playwright context."""
        if not self._http_client:
            return

        cookies = []
        domain = f"{self.hotel_id}.{self.base_domain}"

        for cookie in self._http_client.cookies.jar:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
                "secure": cookie.secure,
                "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
                "sameSite": "Lax",
            })

        if cookies:
            await context.add_cookies(cookies)
            logger.debug("Cookies synced to Playwright", count=len(cookies))

    async def _restore_session(self, context: BrowserContext) -> None:
        """Restaura sesión desde datos guardados."""
        if not self._session_data:
            return

        # Crear cliente HTTP temporal para restaurar cookies
        await self.initialize_http_client()

        # Nota: restaurar cookies en httpx desde SessionData es complejo
        # Por simplicidad, confiamos en las cookies de Playwright
        logger.debug("Session restore requested")

    async def _verify_session(self, context: BrowserContext) -> bool:
        """Verifica que la sesión es válida navegando al calendario."""
        try:
            page = await context.new_page()
            try:
                await page.goto(
                    self.urls.calendar_url(),
                    wait_until="domcontentloaded",
                    timeout=Timeouts.NAVIGATION,
                )

                # Verificar que no redirige a login
                if "login" in page.url.lower():
                    return False

                # Verificar elemento característico del calendario
                try:
                    await page.wait_for_selector(
                        "table.calendar_table",
                        timeout=Timeouts.SELECTOR,
                    )
                    return True
                except PlaywrightTimeoutError:
                    logger.warning("Calendar table not found after login")
                    return False

            finally:
                await page.close()

        except Exception as e:
            logger.warning("Session verification failed", error=str(e))
            return False

    async def ensure_valid_session(self, context: BrowserContext) -> bool:
        """
        Asegura que la sesión es válida, re-logueando si es necesario.
        Llamar antes de cada operación de scraping.
        """
        if await self._verify_session(context):
            return True

        logger.info("Session expired, re-logging in")
        self._session_data = None
        return await self.login(context, force=True)

    async def get_cookies(self) -> list[dict]:
        """Obtiene cookies actuales para persistencia."""
        if self._session_data:
            return self._session_data.cookies
        return []

    def is_logged_in(self) -> bool:
        """Verifica si hay sesión activa (sin verificar validez)."""
        return self._session_data is not None and not self._session_data.is_expired()


class SessionManager:
    """
    Gestor de sesiones persistentes (cache/DB).
    Permite compartir sesiones entre workers.
    """

    def __init__(self, cache):
        self.cache = cache

    def _session_key(self, hotel_id: str, username: str) -> str:
        return f"session:{hotel_id}:{username}"

    async def save_session(self, auth: OtelMSAuth) -> bool:
        """Guarda sesión en cache."""
        if not auth._session_data:
            return False

        key = self._session_key(auth.hotel_id, auth.username)
        data = {
            "cookies": auth._session_data.cookies,
            "user_agent": auth._session_data.user_agent,
            "hotel_id": auth._session_data.hotel_id,
            "username": auth._session_data.username,
            "created_at": auth._session_data.created_at,
            "expires_at": auth._session_data.expires_at,
        }
        return await self.cache.set(key, data, ttl=3600)

    async def load_session(self, hotel_id: str, username: str) -> SessionData | None:
        """Carga sesión desde cache."""
        key = self._session_key(hotel_id, username)
        data = await self.cache.get(key)
        if data:
            return SessionData(**data)
        return None

    async def delete_session(self, hotel_id: str, username: str) -> bool:
        """Elimina sesión del cache."""
        key = self._session_key(hotel_id, username)
        return await self.cache.delete(key)
