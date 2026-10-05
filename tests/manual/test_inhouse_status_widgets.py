"""Estructura de /reservation_c2/status ("Escritorio"): ¿dónde está el in-house?

No usa tablas sino divs, así que se mapean los contenedores con clase y los
bloques de texto que parecen listados. Sale del menú del calendario junto a
rlist/restrict_calendar/price_calendar.

Ejecutar:  env -u PYTHONPATH .venv/Scripts/python.exe -m tests.manual.test_inhouse_status_widgets
"""

import asyncio
from collections import Counter

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import login_client

URL = "https://desktop.otelms.com/reservation_c2/status"


async def main() -> None:
    settings = get_settings()
    client = await login_client(
        "18330",
        settings.otelms_default_username,
        settings.otelms_default_password,
    )
    try:
        resp = await client.get(URL, timeout=30.0)
        soup = BeautifulSoup(resp.text, "lxml")

        print(f"{resp.status_code} · {len(resp.text)} bytes")

        clases = Counter(
            c for tag in soup.find_all(class_=True) for c in tag.get("class", [])
        )
        print("\n=== clases mas frecuentes ===")
        for clase, n in clases.most_common(30):
            print(f"  {n:>4}  {clase}")

        print("\n=== bloques de texto (posibles widgets) ===")
        for div in soup.find_all("div", class_=True):
            textos = div.get_text(" ", strip=True)
            if 10 < len(textos) < 300 and len(div.find_all(True)) <= 4:
                print(f"  [{'.'.join(div.get('class'))}] {textos[:150]}")

        print("\n=== enlaces con texto (menus) ===")
        vistos = set()
        for a in soup.find_all("a", href=True):
            texto = a.get_text(" ", strip=True)
            if not texto or texto in vistos:
                continue
            vistos.add(texto)
            print(f"  {texto[:40]:<40} -> {a['href']}")
    finally:
        await client.aclose()


asyncio.run(main())