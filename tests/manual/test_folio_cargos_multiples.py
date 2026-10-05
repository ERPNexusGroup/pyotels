"""
Comprueba la tabla de cargos cuando hay más de una línea, para
descifrar las columnas 'Número', 'Precio' y 'Cantidad'.

Por qué existe: en las reservas vistas hasta ahora la línea de cargo
tiene Descripción vacía, y parse_folio accede a las columnas por
posición DESPUÉS de quitar las vacías. Eso hace que 'Cantidad' acabe
leyendo la celda correcta solo por casualidad: en cuanto Descripción
traiga algo, todo se desplaza una posición y el importe se lee de la
columna equivocada. El caso de pagos ya ha confirmado que no es una
sospecha teórica.

Este script usa la reserva con más cargos para ver qué pasa con
descripciones pobladas y con cantidades distintas de 1, que es donde
el mapeo tiene que acertar.

Qué mirar: si 'Precio' es precio unitario y 'Cantidad' es el total de
la línea (Precio × unidades), o si hay una columna de unidades
apropiada que se estaba ignorando.

Cómo ejecutarlo:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_folio_cargos_multiples.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from otelms.config.settings import get_settings  # noqa: E402
from otelms.services.calendar_sync_service import CalendarSyncService  # noqa: E402

HOTEL_ID = "18330"
FOLIO_BASE = "https://desktop.otelms.com/reservation_c2/folio"
CANDIDATOS = ["23354", "23564", "23560"]


def main() -> None:
    settings = get_settings()
    session = CalendarSyncService._login(settings, HOTEL_ID)

    for resid in CANDIDATOS:
        resp = session.get(f"{FOLIO_BASE}/{resid}", timeout=30)
        if resp.status_code != 200:
            print(f"{resid}: HTTP {resp.status_code}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        tables = soup.find_all("table")

        print(f"\n{'=' * 70}\nRESERVA {resid}\n{'=' * 70}")

        # Cabecera real de la tabla de cargos, leída sólo de la fila <thead>/<tr>
        # que corresponde a los encabezados de columna, no del pie.
        if len(tables) > 1:
            head_row = tables[1].find("tr")
            headers = (
                [th.get_text(strip=True) for th in head_row.find_all("th")]
                if head_row
                else []
            )
            print(f"cabecera cargos ({len(headers)}):")
            for i, h in enumerate(headers):
                print(f"  [{i}] {h}")

            print("filas de cargos (índice de celda con su cabecera):")
            for row in tables[1].find_all("tr")[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if not any(cells):
                    continue
                if any("Total:" == c for c in cells):
                    print(f"  (fila de total) {cells}")
                    continue
                print(f"  celdas: {cells}")
                for i, cell in enumerate(cells):
                    label = headers[i] if i < len(headers) else "?"
                    if cell:
                        print(f"      [{i}] {label!r} = {cell!r}")

        # Tabla resumen de servicios al pie del folio (Услуга / Сумма / К оплате)
        if len(tables) > 10:
            print("\ntabla resumen final:")
            for row in tables[10].find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if any(cells):
                    print(f"  {cells}")


if __name__ == "__main__":
    main()