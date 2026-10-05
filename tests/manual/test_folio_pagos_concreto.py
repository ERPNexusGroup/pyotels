"""
Vuelca las filas crudas de la tabla de pagos de las reservas que sí
tienen algo en ella.

Por qué existe: el script anterior solo se detuvo en la primera reserva
con filas, y resultó ser una cuyo único contenido era la fila de
total ('Total:', '0.00') — es decir, sin pagos reales. Estas cinco
reservas (23356, 23514, 23560, 23550, 23299) tienen una fila más, que
debe ser una transacción verdadera. Es el único sitio donde se puede
ver cómo se ve un pago de verdad y, por tanto, la única forma de
escribir el mapeo sin inventarlo.

Qué mirar: cómo viene la fecha (formato y si trae hora), qué ocupa la
columna 'Cantidad' de un pago, y si hay pagos negativos o
anulaciones que haya que filtrar.

Cómo ejecutarlo:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_folio_pagos_concreto.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from otelms.config.settings import get_settings  # noqa: E402
from otelms.services.calendar_sync_service import CalendarSyncService  # noqa: E402

HOTEL_ID = "18330"
FOLIO_BASE = "https://desktop.otelms.com/reservation_c2/folio"
CANDIDATOS = ["23356", "23514", "23560", "23550", "23299"]


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
        if len(tables) < 3:
            print(f"{resid}: solo {len(tables)} tablas")
            continue

        header = [th.get_text(strip=True) for th in tables[2].find_all("th")]
        print(f"\n{'=' * 70}\nRESERVA {resid}\n{'=' * 70}")
        print(f"cabecera pagos ({len(header)} columnas):")
        for i, h in enumerate(header):
            print(f"  [{i}] {h}")

        print("filas:")
        for row in tables[2].find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if any(cells):
                print(f"  {cells}")

        path = Path(__file__).parent / f"folio_pagos_{resid}.html"
        path.write_text(resp.text, encoding="utf-8")


if __name__ == "__main__":
    main()
