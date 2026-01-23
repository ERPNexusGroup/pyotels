from playwright.sync_api import TimeoutError, Error


class PlaywrightTimeoutError(TimeoutError):
    """Problemas de conexión o timeouts."""
    pass


class PlaywrightError(Error):
    """Problemas de conexión o timeouts."""
    pass
