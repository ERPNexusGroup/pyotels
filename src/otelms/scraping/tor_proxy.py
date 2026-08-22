"""Gestor de proxy Tor con rotación de IP para pruebas de login anti-bloqueo.

Usa Tor SOCKS5 (127.0.0.1:9050) para routing y stem (ControlPort 9051) para rotar
circuito. Cada `rotate_circuit()` reinicia el circuito obteniendo una IP fresca.
"""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from stem import Signal
from stem.control import Controller

from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class TorProxyManager:
    """Singleton que maneja un proxy Tor local con rotación de IPs.

    Uso:
        async with TorProxyManager() as tor:
            proxy_url = tor.proxy_url  # socks5h://127.0.0.1:9050
            await tor.rotate_circuit()     # IP nueva
    """

    SOCKS_PORT = 9050
    CONTROL_PORT = 9051
    PROXY_URL = f"socks5h://127.0.0.1:{SOCKS_PORT}"

    def __init__(self, password_base: str = "harmony-hotel-tor-training"):
        self._controller: Controller | None = None
        self._password = hashlib.sha256(password_base.encode()).hexdigest()
        self._last_rotation: float = 0
        # Mínimo 5 segundos entre rotaciones para no floodear Tor
        self._cooldown: float = 5.0

    @property
    def proxy_url(self) -> str:
        """URL SOCKS5 para httpx/Playwright."""
        return self.PROXY_URL

    async def __aenter__(self) -> "TorProxyManager":
        """Conectar a Tor controller."""
        self._controller = await asyncio.to_thread(
            Controller.from_port,
            port=self.CONTROL_PORT,
        )
        self._controller.authenticate(password=self._password)
        logger.info("Tor controller authenticated")
        return self

    async def __aexit__(self, *args) -> None:
        if self._controller:
            self._controller.close()
            self._controller = None

    async def rotate_circuit(self) -> bool:
        """Rotar el circuito Tor para obtener IP nueva.

        Returns:
            True si la rotación exitosa, False si en cooldown.
        """
        elapsed = datetime.now(UTC).timestamp() - self._last_rotation
        if elapsed < self._cooldown:
            logger.debug("Tor rotation cooldown", remaining=round(self._cooldown - elapsed, 1))
            return False

        if not self._controller:
            await self.__aenter__()

        # NUEVO CIRCUITO (limpia IP vieja)
        self._controller.signal(Signal.NEWNYM)
        self._last_rotation = datetime.now(UTC).timestamp()
        logger.info("Tor circuit rotated — new IP")
        return True

    async def verify_proxy(self) -> str | None:
        """Verificar que la proxy funciona devolviendo la IP actual."""
        import httpx

        async with httpx.AsyncClient(proxy=self.PROXY_URL, timeout=httpx.Timeout(10)) as client:
            resp = await client.get("https://httpbin.org/ip")
            if resp.status_code == 200:
                ip = resp.json()["origin"]
                logger.debug("Tor proxy IP", ip=ip)
                return ip
            return None


# Singleton global (opcional, usar dentro de pruebas como fixture)
_tor_manager: TorProxyManager | None = None


def get_tor_manager() -> TorProxyManager:
    """Obtener singleton global."""
    global _tor_manager
    if _tor_manager is None:
        _tor_manager = TorProxyManager()
    return _tor_manager