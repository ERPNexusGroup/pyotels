"""
Políticas de retry con tenacity para scraping robusto.
"""
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    wait_fixed,
)

from otelms.config.settings import settings
from otelms.scraping.exceptions import (
    AuthenticationError,
    BrowserError,
    NavigationError,
    RateLimitError,
    ScrapingError,
    SessionExpiredError,
)
from otelms.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def is_retryable_error(exc: Exception) -> bool:
    """Determina si un error es reintentable."""
    # No reintentar errores de autenticación (credenciales inválidas)
    if isinstance(exc, AuthenticationError) and not isinstance(exc, SessionExpiredError):
        return False

    # No reintentar rate limit (se maneja por rate limiter)
    if isinstance(exc, RateLimitError):
        return False

    # Reintentar errores de navegación, extracción, browser
    if isinstance(exc, (NavigationError, BrowserError)):
        return True

    # Reintentar errores genéricos de scraping
    if isinstance(exc, ScrapingError):
        return True

    # Reintentar errores de red/conexión
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    return False


def before_sleep_log_retry(retry_state: RetryCallState) -> None:
    """Log antes de reintentar."""
    if retry_state.outcome and retry_state.outcome.exception():
        exc = retry_state.outcome.exception()
        logger.warning(
            "Retrying scraping operation",
            attempt=retry_state.attempt_number,
            error_type=type(exc).__name__,
            error=str(exc),
            wait_time=retry_state.next_action.sleep if retry_state.next_action else 0,
        )


# Retry policy estándar para operaciones de scraping
scraping_retry = AsyncRetrying(
    retry=retry_if_exception_type((
        NavigationError,
        BrowserError,
        ConnectionError,
        TimeoutError,
        OSError,
    )),
    wait=wait_exponential_jitter(
        initial=settings.scraper_retry_base_delay,
        max=settings.scraper_retry_max_delay,
        jitter=settings.scraper_retry_jitter,
    ),
    stop=stop_after_attempt(settings.scraper_max_retries),
    before_sleep=before_sleep_log_retry,
    reraise=True,
)


# Retry policy agresivo para login (menos intentos, más rápido)
login_retry = AsyncRetrying(
    retry=retry_if_exception_type((
        NavigationError,
        BrowserError,
        SessionExpiredError,
        ConnectionError,
        TimeoutError,
    )),
    wait=wait_fixed(2),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log_retry,
    reraise=True,
)


# Retry policy para navegación de páginas
navigation_retry = AsyncRetrying(
    retry=retry_if_exception_type((
        NavigationError,
        BrowserError,
        ConnectionError,
        TimeoutError,
    )),
    wait=wait_exponential_jitter(
        initial=1.0,
        max=10.0,
        jitter=True,
    ),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log_retry,
    reraise=True,
)


async def with_retry[T](
    func: Callable[..., Awaitable[T]],
    *args,
    retry_policy: AsyncRetrying = scraping_retry,
    **kwargs,
) -> T:
    """
    Ejecuta una función con política de retry.
    """
    return await retry_policy(func, *args, **kwargs)


class RetryContext:
    """Context manager para operaciones con retry personalizado."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (
            NavigationError,
            BrowserError,
            ConnectionError,
            TimeoutError,
        ),
    ):
        self.retry_policy = AsyncRetrying(
            retry=retry_if_exception_type(*retryable_exceptions),
            wait=wait_exponential_jitter(
                initial=base_delay,
                max=max_delay,
                jitter=jitter,
            ),
            stop=stop_after_attempt(max_attempts),
            before_sleep=before_sleep_log_retry,
            reraise=True,
        )

    async def __call__(self, func: Callable[..., T], *args, **kwargs) -> T:
        return await self.retry_policy(func, *args, **kwargs)

    async def __aenter__(self) -> "RetryContext":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False  # No suprimir excepciones
