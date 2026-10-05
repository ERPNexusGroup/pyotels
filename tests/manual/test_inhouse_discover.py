"""Descubrimiento: ¿existe un endpoint de in-house en OtelMS?

No se inventa la URL. Este script entra al portal, saca todos los `href` de la
página de aterrizaje y del menú, y filtra los que suenen a in-house /
hospedados / alojados para proponer una URL verificada en vez de adivinada.

Ejecutar:  env -u PYTHONPATH .venv/Scripts/python.exe -m tests.manual.test_inhouse_discover
"""

import asyncio
import re
from collections import Counter
from urllib.parse import urljoin

import httpx

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import login_client

PATRONES = re.compile(
    r"in[-_ ]?house|hosped|alojad|occupied|ocupad|stay|reside|current",
    re.IGNORECASE,
)

BASE = "https://desktop.otelms.com"


async def main() -> None:
    settings = get_settings()
    urls = OtelMSUrls("otelms.com", "18330")
    client = await login_client(
        "18330",
        settings.otelms_default_username,
        settings.otelms_default_password,
    )

    try:
        for nombre, url in (
            ("landing", urls.base_url + "/"),
            ("calendar", urls.calendar_url()),
            ("reservas", f"{BASE}/reservation_c2/"),
        ):
            try:
                resp = await client.get(url, timeout=30.0)
            except Exception as exc:  # noqa: BLE001 - es un script de sondeo
                print(f"{nombre}: error {exc}")
                continue

            html = resp.text
            hrefs = re.findall(r'href=["\']([^"\']+)["\']', html)
            propios = sorted({
                urljoin(BASE, h) for h in hrefs
                if h.startswith("/") and not h.startswith("//")
            })
            print(f"\n=== {nombre} ({resp.status_code}, {len(html)} bytes, "
                  f"{len(propios)} enlaces propios) ===")
            print("destino final:", str(resp.url))
            for enlace in propios:
                print("  ", enlace)

            candidatos = [e for e in propios if PATRONES.search(e)]
            if candidatos:
                print(f"  --> candidatos in-house ({len(candidatos)}):")
                for c in candidatos:
                    print("      *", c)

            # El menú suele estar en texto, no en la URL.
            for linea in re.findall(r'>([^<>]{3,40})<', html):
                if PATRONES.search(linea):
                    print("   texto:", linea.strip())

        print("\n=== rutas mas repetidas en el landing ===")
        landing = (await client.get(urls.base_url + "/", timeout=30.0)).text
        conteo = Counter(
            re.findall(r'href=["\'](/[^"\'#?]+)', landing)
        )
        for ruta, n in conteo.most_common(25):
            print(f"  {n:>3}  {ruta}")
    finally:
        await client.aclose()


asyncio.run(main())