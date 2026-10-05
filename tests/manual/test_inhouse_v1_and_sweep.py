"""Cierre de la investigación de in-house (Tarea 1.4).

1. `/reservations/calendar/` ("HMS v1.0" / "Tabla de reservas") — última ruta
   del menú sin sondear.
2. Recorre todas las páginas de `/reservation_c2/rlist/{n}` y reparte la columna
   `Estado` para ver si "Check in" es exactamente el in-house.
"""

import asyncio
from collections import Counter
from datetime import date, timedelta

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import login_client

BASE = "https://desktop.otelms.com"
HOY = date.today().isoformat()


async def main() -> None:
    settings = get_settings()
    client = await login_client(
        "18330",
        settings.otelms_default_username,
        settings.otelms_default_password,
    )
    try:
        # --- 1. La ruta sin sondear -------------------------------------
        for ruta in ("/reservations/calendar/", "/reservation_c2/group_reservation"):
            resp = await client.get(f"{BASE}{ruta}", timeout=30.0)
            soup = BeautifulSoup(resp.text, "lxml")
            tablas = soup.find_all("table")
            print(f"\n=== {ruta} -> {resp.status_code} · {len(resp.text)} bytes · "
                  f"{len(tablas)} tablas ===")
            print("title:", soup.title.get_text(strip=True) if soup.title else None)
            for i, tabla in enumerate(tablas[:3]):
                filas = tabla.find_all("tr")
                cab = [c.get_text(strip=True) for c in filas[0].find_all(["th", "td"])] if filas else []
                print(f"  tabla {i}: {max(len(filas) - 1, 0)} filas | {cab[:12]}")

        # --- 2. Estados reales en toda la lista --------------------------
        estados = Counter()
        checked_in = []
        for pagina in range(1, 40):
            resp = await client.get(f"{BASE}/reservation_c2/rlist/{pagina}", timeout=30.0)
            tabla = BeautifulSoup(resp.text, "lxml").find("table")
            filas = tabla.find_all("tr") if tabla else []
            if len(filas) < 2:
                break
            cabeceras = [c.get_text(strip=True) for c in filas[0].find_all(["th", "td"])]
            idx = {n: i for i, n in enumerate(cabeceras)}
            for f in filas[1:]:
                c = f.find_all("td")
                if len(c) <= idx["Estado"]:
                    continue
                estado = c[idx["Estado"]].get_text(strip=True)
                estados[estado] += 1
                if estado == "Check in":
                    checked_in.append({
                        "res": c[idx["Reserva"]].get_text(strip=True),
                        "hab": c[idx["Habitación"]].get_text(strip=True),
                        "huesped": c[idx["Huésped"]].get_text(strip=True),
                        "entrada": c[idx["Entrada"]].get_text(strip=True),
                        "salida": c[idx["Salida"]].get_text(strip=True),
                    })

            total_paginas = len({a["href"] for a in
                                 BeautifulSoup(resp.text, "lxml").find_all("a", href=True)
                                 if "reservation_c2/rlist/" in a["href"]})
            if pagina > 8 and pagina >= total_paginas:
                break

        print(f"\n=== estados en {pagina} paginas ({sum(estados.values())} reservas) ===")
        for estado, n in estados.most_common():
            print(f"  {n:>4}  {estado}")

        print(f"\n=== in-house 후보: {len(checked_in)} reservas 'Check in' "
              f"(hoy = {HOY}) ===")
        for row in checked_in[:20]:
            print("   ", row)

        fuera = [r for r in checked_in
                 if not (r["entrada"] <= HOY < r["salida"])]
        print(f"\nde las cuales NO cubren hoy (entrada <= hoy < salida): "
              f"{len(checked_in) - len(fuera)}")
        for row in fuera[:10]:
            print("    fuera:", row)
    finally:
        await client.aclose()


asyncio.run(main())