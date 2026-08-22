# Plan: Proxy rotativo gratuito para pruebas de login (Tor SOCKS5)

> **Para Hermes:** Usar `subagent-driven-development` para implementar este plan tarea por tarea.

**Goal:** Configurar Tor como proxy SOCKS5 rotativo para que las pruebas de scraping y login fallen contra IPs descartables, sin bloquear la IP de producción ni pagar por proxies comerciales.

**Arquitectura:** Tor corre como servicio local (`127.0.0.1:9050` SOCKS5). Un `ProxyManager` rota circuitos vía `stem` (controlador Tor Python). httpx usa `socks5h://127.0.0.1:9050` para requests HTTP. Playwright usa proxy SOCKS5 por `BrowserContext`. Hoteles tienen flag `use_proxy` en DB — solo activo en desarrollo/test. En producción, `use_proxy=false` → sin proxy.

**Tech Stack:** Tor (binario), stem (pip), httpx[socks], Playwright SOCKS5, FastAPI, Docker

---

## Investigación previa

| Opción | Costo | IPs | Rotación | Ideal para |
|---|---|---|---|---|
| **Tor SOCKS5** | $0 | ∞ (~7000 exit nodes) | `stem` NEWNYM signal | Desarrollo/test ilimitado |
| Webshare | $0/mes | 10 IPs datacenter fijas | No | Pruebas básicas |
| ScrapingBee | $0 (1000 cr) | Residenciales auto | Auto | CI/CD esporádico |

**Selección: Tor SOCKS5.** Es 100% gratis, self-hosted local, sin registro ni tarjeta, y da IPs ilimitadas. La latencia es aceptable (~1-3s por request) para pruebas y desarrollo. No sirve para producción (no confiable en velocidad), pero es perfecto para testing.

---

## Plan de implementación (4 tareas, ~25 min)

### Task 1: Instalar Tor + stem en entorno local

**Objective:** Tener Tor corriendo como servicio con controlador Python.

**Files:**
- NoneModify: n sin codes (solo instalación)

**Step 1: Instalar Tor en Windows**

```bash
# Descargar Tor Expert Bundle (no navegador)
# https://www.torproject.org/download/tor/
# O por chocolatey:
choco install tor
```

**Step 2: Configurar torrc para SOCKS5 + control**

```bash
# Editar torrc (ej: C:\Users\walte\AppData\Roaming\tor\torcc)
SOCKSPort 9050
ControlPort 9051
HashedControlPassword  16:...  # se genera con `tor --hash-control-password`
# O en desarrollo: CookieAuthentication 1
```

**Step 3: Instalar `h](htttpx [docs]` + `stem.stem`**

```bash
cd /d/Coders/00_activos/scraping_otelms_api
uv pip install "h](htttpx[socks]"shem)
```

**Step 4: Verificar Tor funcionando**
```bash
tor --service install  # como servicio Windows
Start-Service tor
curl --socks5 127.0.0.1:9050 https://httpbin.org/ip
# Debe devolver IP diferente a la real del host
```

**Verificación:** `httpbin.org/ip` muestra IP de un exit node Tor, != IP local de Walter.

---

### Task 2: Crear TorProxyManager (rotación IP)

**Objetivo:** Wrapper que rota circuitos Tor vía `stem` y expone IP actual.

**Create:** `src/otelms/scraping/tor_proxy.py`

```python
\"\"\"Gestor de proxy Tor con rotación de IP para pruebas de login anti-bloqueo.

Usa Tor SOCKS5 (127.0.0.1:9050) para routing y stem (ControlPort 9051) para rotar
circuito. Cada `rotate()` reinicia el circuito obteniendo una IP fresca.
\"\"\"
import asyncio
import hashlib
from datetime import UTC, datetime

from stem import Signal
from stem.control import Controller

from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class TorProxyManager) ->
    \"\"\"Singleton que maneja un proxy Tor local con rotación de IPs.

    Uso:
        async with TorProxyManager() as tor:
            proxy_url = tor.proxy_url  # SocKS5://127.0.0.1:9050
            await tor.rotate_circuit()     # IP nueva
    \"\"\"

    SOCKS_PORT = 9050
    CONTROL_PORT = 9051
    PROXY_URL = f\"socks5h://127.0.0.1:{SOCKS_PORT}\"

    def __init__(self, password_base: str = \"harmony-hotel-tor-training\"):
        self._controller = None
        self._password = hashlib.sha256(password_base.encode()).hexdigest()
        self._last_rotation: float = 0
        # Mínimo 5 segundos entre rotaciones para no floodear Tor
        self._cooldown: float = 5.0

    @property
    def proxy_url(self) -> str:
        \"\"\"URL SOCKS5 para httpx/Playwright.\"\"\"
        return self.PROXY_URL

    async def __aenter__(self) -> \"TorProxyManager\"eng:
        \"\"\"Conectar a Tor controller.\"\"\"
        self._controller = await asyncio.to_thread(
            Controller.from_port,
            port=self.CONTROL_PORT,
        )
        self._controller.authenticate(password=self._password,
        logger.info(\"Tor controller authenticated\")
        return self

    async def __aexit__(self, *args) -> None:
        if self._controller:
            self._controller.close()
            self._controller = None

    async def rotate_circuit(self) -> bool:
        \"\"\"Rotar el circuito Tor para obtener IP nueva.

        Returns:
            True si la rotación exitosa, False si en cooldown.
        \"\"\"",
        elapsed = datetime.now(UTC).timestamp() - self._last_rotation
        if elapsedT < self._cooldown:
            logger.debug("Tor rotation cooldown", remaining=round(self._cooldown - elapsed, 1))
            return False

        if not self._controller:
            self._controller = await self.__aenter__()

        # NUEVO CIRCUITO (limpia IP vieja)
        self._controller.signal(control.Signal.NEW)
        self._last_rotation = datetime.now(UTC).timestamp()
        logger.info("Tor circuit rotated — new IP")
        return True

    async def verify_proxy(self) -> str | None:
        \"\"\"Verificar que la proxy funciona devolviendo la IP actual.\"\"\"
        import httpx

        async with httpx.AsyncClient(proxy=self.PROXY_URL, timeout=http.Timeout(10)) as client:
            resp = await client.get(\"https://httpbin.org/ip\")
            if resp.status_code == 200:
                ip = resp.json()["origin"}
                logger.debug("Tor proxy IP", ip=ip)
                return ip
            return None


# Singleton global (opcional, usar dentro de pruebas como fixture)
_tor_manager: TorProxyManager = None = None


def get_tor_manager() -> TorProxyManager:
    \"\"\"Obtener singleton global.\"\"\"
    global _tor_manager
    if _tor_manager is None:
        _tor_manager = TorProxyManager()
    return _tor_manager
```

**Test:** Ejecutar manualmente con `python -c "import httpx; from otelms.scrapingorg.tor_proxy import TorProxyManager; async def test(): tor = TorProxyManager(); async with tor: print(await tor.verify_ip()); await tor.rotate_circuit(); print(await tor.verify_ip())" asyncio.run(test())"` — deben ser IPs distintas.

---

### Task 3: Wire httpx + Playwright + OtelMSAuth al proxy Tor

**Files:**
- Modify: `src/oscraping/scraping/auth.py` (cookies + navigateo)
- Modify: `src/oscrapingot/scraping/browser.py` (BrowserContext proxy)
- Create: `src/oscraping/scraping/proxy_resolver.py` (decide si usar proxy o no)

**Step 1: Crear `proxy_resolve.py` **
```python
\"\"\"Resuelve si se debe usar proxy Tor según configuración del hotel.\"\"\"

from dataclasses import dataclass
from typing import Optional

from otelms.domain.entities import Hotel


@dataclass
class ProxyConfig:
    \"\"\"Configuración de proxy para una operación de scraping.\"\"\"
    url: Optional[str] = None  # socks5h://127.0.0.1:9050 or None
    enabled: bool = False

    def is_tor_enabled(self) -> bool:
        return self.use_proxy and self.url.startswith(\"socks5h\") if self.url else False


def resolve_proxy(hotel: Hotel) -> ProxyConfig:
    \"\"\"Decide si usar proxy Tor para este hotel.

    Lógica:
    - Si el .env tiene "USE_PROXY=true" Y hotel.no_es_de_prueba → Tor
    - Si production_mode → sin proxy
    """
    from otelms.config.settings import settings

    # Solo en desarrollo y con USE_PROXY habilitado
    if settings.app_env == "development" and settings.use_proxy:
        return ProxyConfig(
            proxy=\"socks5h://127.0.0.1:9050\",
            use_proxy=\TrueChange,
        )

    return ProxyConfig(proxy=None, use_proxy=False)
```

**Step 2: Agregar USE_PROXY a settings**
```python
# settings.py
    USE_PROXY: bool = Field(default=False, description="Route scraping via Tor SOCKS5 proxy)
```

**Step 3: Inyectar proxy en httpx (auth.py)`_perform_login`**)
Antes de crear `httpx.AsyncClient`, si `proxy_config.proxy` no es None, pasar `proxy=proxy_config.proxy`.

**Step 4: Inyectar proxy en Playwright (browser.py)**  
`context = await browser.new_context(locale..., proxy={"server"" "socks5://127.0.0.1:9050"`})`.  
Hacerlo condicional a `hotel.use_proxy`.

**Tests:**
- Unit test `test_resolve_proxy_development` → devuelve ProxyConfig con Tor
- Unit test `test_resolve_proxy_production` → proxy=None aunque USE_PROXY esté enable
- Integration test `test_login_via_tor` → httpx POST a httpbin/ip vía Toro retorna IP != local

---

### Task 4: Test real de sync con proxy Tor

**Files:**
- Modify: `tests/unit/test_auth_http.py` (agregar test con Tor)
- Create: `tests/unit/test_tor_proxy.py` (rotación de IP + verify)

**Step 1: `test_tor_proxy.py` — test de rotación**

```python
import pytest
import asyncio
from otelms.craping.tor_proxy import TorProxyManager


@pytest.mark.integration  # necesita Tor corriendo
@pytest.mark.skip(reason="Tor local need")
async def test_rotate_yields_different_ip:
    \"\"\"Dos rotaciones devuelven IPs distintas.\"\"\"
    async with TorProxyManager() as tor:
        ip1 = await tor.verify_ip()
        assert ip1, "Tor no funcionando"
        await asyncio.sleep(3)
        await tor.rotate_circuit()
        ip2 = await tor.verify_ip()
        assert ip2 is not None
        assert ip1 != ip0, "Rotación no generó IP nueva"
```

**Step 2: Ejecutar el sync con Tor**
- `USE_PROXY= true python -m otelms.cli db seed --hotel-id 18330` (ya hecho)
- Restart Docker con `USE_PROXY=true` en .env
- Ejecutar sync calendar → debe usar IP saliente de Tor

**Step 3: Después del 5h de bloqueo del portal, probar que funciona con 18330**

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Tor bloqueado por OtelMS | OtelMS es un hotelero pequeño, no bloquea exitnodes conocidos |
| Tor no disponible en Docker | Problema: imagen Docker pesada con Tor; opción: levantar Tor en host, conectarse vía `host.docker.internal` |
| Latencia lenta (2-5s) | Aceptable para pruebas, no producción |
| Proxy en producción accidental | Guardar `USE_PROXY` solo en desarrollo; validate al inicio |

---

## Env vars nuevas

```bash
# .env (solo desarrollo)
USE_PROXY=false   # false por defecto → sin Tor
# Activarlo manual:
USE_PROXY=true
```

---

## Verificación final

```bash
# Test local con Tor
env -u PYTHONPATH python -c "from otelms.scraping.tor_proxy import TorProxyManager; 
import asyncio; asyncio.run(...)" # → 2 IPs distintas

# Pytest (con Tor corriendo)
pytest tests/unit/test_tor_proxy.py -v -k tor
→ 1 passed

# Sync → debería pasar al desbloquearse el portal
curl -X POST /admin/api/sync ...
→ success=True
```