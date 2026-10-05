"""Sondeo de /reservation_c2/status: ¿es la vista de in-house?

Salen del menú del calendario. Se dumpean las tablas con su cabecera real (por
nombre de columna, nunca por posición) para ver si es el listado de hospedados.

Ejecutar:  env -u PYTHONPATH .venv/Scripts/python.exe -m tests.manual.test_inhouse_status
"""

import asyncio

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import login_client

BASE = "https://desktop.otelms.com"

RUTAS = (
    "/reservation_c2/status",
    "/reservation_c2/rlist/1",
    "/reservation_c2/restrict_calendar",
    "/reservation_c2/price_calendar",
)


async def main() -> None:
    settings = get_settings()
    client = await login_client(
        "18330",
        settings.otelms_default_username,
        settings.otelms_default_password,
    )
    try:
        for ruta in RUTAS:
            resp = await client.get(f"{BASE}{ruta}", timeout=30.0)
            soup = BeautifulSoup(resp.text, "lxml")

            tablas = soup.find_all("table")
            print(f"\n=== {ruta} -> {resp.status_code} "
                  f"({len(resp.text)} bytes, {len(tablas)} tablas) ===")
            print("title:", soup.title.get_text(strip=True) if soup.title else None)

            for i, tabla in enumerate(tablas):
                filas = tabla.find_all("tr")
                if not filas:
                    continue
                cabecera = [
                    c.get_text(strip=True)
                    for c in filas[0].find_all(["th", "td"])
                ]
                cuerpo = len([f for f in filas[1:]])
                print(f"  tabla {i}: {cuerpo} filas | columnas: {cabecera}")
                for f in filas[1:3]:
                    vals = [c.get_text(strip=True)[:28] for c in f.find_all("td")]
                    if vals:
                        print(f"      ej: {vals}")

            # Enlaces a reservas/huéspedes desde la vista.
            enlaces = [
                a.get("href")
                for a in soup.find_all("a", href=True)
                if "/folio/" in a["href"] or "/guestfolio/" in a["href"]
                or "/edit/" in a["href"]
            ]
            if enlaces:
                print(f"  enlaces a reservas: {len(enlaces)} -> {enlaces[:5]}")
    finally:
        await client.aclose()


asyncio.run(main())