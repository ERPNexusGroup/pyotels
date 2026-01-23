from playwright.sync_api import Page

from pyotels.exceptions.playwright_error import PlaywrightTimeoutError


def wait_for_selector_with_retry(
    page: Page,
    selector: str,
    *,
    state: str = "visible",
    base_timeout: int,
    retries: int = 3,
    backoff: float = 1.5
):
    last_error = None

    for attempt in range(1, retries + 1):
        timeout = int(base_timeout * (backoff ** (attempt - 1)))
        try:
            page.wait_for_selector(
                selector,
                state=state,
                timeout=timeout
            )
            return  # éxito
        except PlaywrightTimeoutError as e:
            last_error = e
            page.logger.warning(
                f"Intento {attempt}/{retries} falló esperando '{selector}' "
                f"(timeout={timeout}ms)"
            )

    # si llegamos acá → falló todo
    raise last_error
