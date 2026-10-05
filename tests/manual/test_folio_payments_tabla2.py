"""
Busca una reserva que SÍ tenga pagos, para poder mapear la tabla [2].

Por qué existe: el script anterior sacaba 0 pagos en los tres folios
que miró. Eso tiene dos explicaciones muy distintas — que esas reservas
aún no estén pagadas (normal si son futuras), o que el parser esté
descartando filas. Con la tabla vacía no se puede distinguir una cosa de
la otra, así que hay que ir a buscar una reserva cobrada de verdad.

Qué hace: recorre las reservas del calendario y, en cada folio, mira
si la tabla de pagos tiene filas de datos. Se para en la primera que
tenga, y ahí imprime la fila cruda con todas sus celdas, para poder
escribir el mapeo a ojo en vez de suponerlo.

Cómo ejecutarlo:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_folio_payments_tabla2.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from otelms.config.settings import get_settings  # noqa: E402
from otelms.scraping.folio_extract import extract_reservations_from_calendar  # noqa: E402
from otelms.services.calendar_sync_service import CalendarSyncService  # noqa: E402

HOTEL_ID = "18330"
FOLIO_BASE = "https://desktop.otelms.com/reservation_c2/folio"


def payment_rows(html_text: str) -> list:
    """Filas de datos de la tabla de pagos (índice 2), sin filtrar.

    Se salta la fila de cabecera y devuelve lo que hay, para que el
    caller decida si está vacío de verdad.
    """
    soup = BeautifulSoup(html_text, "lxml")
    tables = soup.find_all("table")
    if len(tables) < 3:
        return []
    rows = tables[2].find_all("tr")[1:]
    out = []
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if any(cells):
            out.append(cells)
    return out


def service_rows(html_text: str) -> list:
    """Filas crudas de la tabla de cargos (índice 1), sin filtrar."""
    soup = BeautifulSoup(html_text, "lxml")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return []
    out = []
    for row in tables[1].find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if any(cells):
            out.append(cells)
    return out


def main() -> None:
    settings = get_settings()
    session = CalendarSyncService._login(settings, HOTEL_ID)

    cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
    reservations = extract_reservations_from_calendar(cal.text)
    print(f"reservas en el calendario: {len(reservations)}")

    found_payments = False
    for res in reservations:
        resid = str(res["resid"])
        resp = session.get(f"{FOLIO_BASE}/{resid}", timeout=30)
        if resp.status_code != 200:
            print(f"  {resid}: HTTP {resp.status_code}")
            continue

        pays = payment_rows(resp.text)
        svcs = service_rows(resp.text)
        print(f"  {resid}: cargos={len(svcs)} pagos={len(pays)}")

        # Muestra la estructura de cargos en la primera reserva, para ver
        # si Descripción/Número vienen vacíos (y el mapeo posicional de
        # parse_folio acierta por casualidad) o poblados (y falla).
        if not found_payments and pays:
            found_payments = True
            print(f"\n{'=' * 70}\nRESERVA {resid} CON PAGOS\n{'=' * 70}")
            print("  cargos (celda a celda, con celdas vacías visibles):")
            for r in svcs:
                print(f"    {r}")
            print("\n  pagos:")
            for r in pays:
                print(f"    {r}")

            path = Path(__file__).parent / f"folio_con_pagos_{resid}.html"
            path.write_text(resp.text, encoding="utf-8")
            print(f"\n  HTML guardado en {path.name}")

    if not found_payments:
        print("\nNinguna reserva del calendario tiene pagos cargados.")
        print("Habría que mirar otro listado (reservas pasadas, o el")
        print("filtro de fechas del calendario) para ver la tabla [2] con datos.")


if __name__ == "__main__":
    main()
