"""¿`/reservation_c2/rlist/{n}` filtra por estado? De ahí sale el in-house.

El menú llama "Informes" a `/reservation_c2/rlist/1`. El `1` puede ser página o
estado: se recorren los valores posibles y se mira qué cambia en la tabla
(primera fila y reparto de la columna `Estado`).

Ejecutar:  env -u PYTHONPATH .venv/Scripts/python.exe -m tests.manual.test_inhouse_rlist
"""

import asyncio
from collections import Counter

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import login_client

BASE = "https://desktop.otelms.com"

VALORES = ("1", "2", "3", "4", "5", "0", "today", "inhouse")


def _columnas(filas):
    if not filas:
        return []
    return [c.get_text(strip=True) for c in filas[0].find_all(["th", "td"])]


async def main() -> None:
    settings = get_settings()
    client = await login_client(
        "18330",
        settings.otelms_default_username,
        settings.otelms_default_password,
    )
    try:
        for valor in VALORES:
            url = f"{BASE}/reservation_c2/rlist/{valor}"
            resp = await client.get(url, timeout=30.0)
            soup = BeautifulSoup(resp.text, "lxml")
            tabla = soup.find("table")
            filas = tabla.find_all("tr") if tabla else []
            cabeceras = _columnas(filas)

            estados = Counter()
            primera = []
            if len(cabeceras) > 13:
                idx_estado = cabeceras.index("Estado")
                for f in filas[1:]:
                    celdas = f.find_all("td")
                    if len(celdas) > idx_estado:
                        estados[celdas[idx_estado].get_text(strip=True)] += 1
                primera = [c.get_text(strip=True)[:22] for c in filas[1].find_all("td")][:8]

            print(f"\n--- rlist/{valor} -> {resp.status_code} · {len(resp.text)} bytes "
                  f"· {len(filas) - 1} filas ---")
            print(f"    columnas: {cabeceras[:8]}")
            print(f"    Estado: {dict(estados)}")
            if primera:
                print(f"    1a fila: {primera}")

            # ¿Aparecen enlaces de paginación?
            paginas = [
                a.get("href") for a in soup.find_all("a", href=True)
                if "rlist" in a["href"] and a.get("href") != f"/reservation_c2/rlist/{valor}"
            ]
            if paginas:
                print(f"    paginación: {sorted(set(paginas))[:8]}")
    finally:
        await client.aclose()


asyncio.run(main())