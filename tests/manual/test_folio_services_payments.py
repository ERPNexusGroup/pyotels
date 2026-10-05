"""
Investiga qué contienen realmente las tablas de cargos y pagos del folio.

Por qué existe: la Tarea 1.3 pide extraer services + payments, pero
`_persist_reservation_details` lee `detail["accommodation"]` y
`detail["services"]`, y el modal del calendario no trae nada de eso.
El endpoint que sí los trae es /reservation_c2/folio/{id}, que ya usan
los scripts de la sesión anterior. Este script comprueba, contra el
portal real, si `parse_folio` mapea las columnas por su posición o se
la está inventando.

Qué mirar en la salida:
  1. Cabeceras reales de cada tabla (una por línea) contra las que
     asume parse_folio. Si no coinciden, el mapeo posicional
     (non_empty[0], [1], [2]...) está leyendo columnas equivocadas.
  2. Que los importes de pagos sumen lo mismo que el saldo del folio.
     Si no cuadran, falta alguna tabla o hay que filtrar anulaciones.

Cómo ejecutarlo:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_folio_services_payments.py
"""

import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from otelms.config.settings import get_settings  # noqa: E402
from otelms.scraping.folio_extract import parse_folio  # noqa: E402
from otelms.services.calendar_sync_service import CalendarSyncService  # noqa: E402

HOTEL_ID = "18330"
FOLIO_BASE = "https://desktop.otelms.com/reservation_c2/folio"
OUT_DIR = Path(__file__).parent
MAX_FOLIOS = 3


def dump_table_headers(html_text: str) -> None:
    """Imprime la cabecera real de cada tabla del folio, en orden.

    parse_folio accede a las tablas por índice (tables[1] = cargos,
    tables[2] = pagos, tables[7] = room charges). Este listado es lo que
    permite comprobar que ese índice sigue apuntando a lo que cree.
    """
    soup = BeautifulSoup(html_text, "lxml")
    tables: Sequence = soup.find_all("table")
    print(f"  tablas en el folio: {len(tables)}")
    for idx, table in enumerate(tables):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [
                    c.get_text(strip=True)
                    for c in first_row.find_all(["td", "th"])
                ]
        joined = " | ".join(h for h in headers if h)
        print(f"    [{idx}] {joined[:150]}")


def main() -> None:
    settings = get_settings()
    session = CalendarSyncService._login(settings, HOTEL_ID)

    cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
    if cal.status_code != 200:
        print(f"El calendario devolvió {cal.status_code}")
        return

    # Los resids salen del propio calendario para no inventarlos.
    from otelms.scraping.folio_extract import extract_reservations_from_calendar

    reservations = extract_reservations_from_calendar(cal.text)
    print(f"reservas en el calendario: {len(reservations)}")
    if not reservations:
        return

    for res in reservations[:MAX_FOLIOS]:
        resid = str(res["resid"])
        print(f"\n{'=' * 70}\nFOLIO {resid}\n{'=' * 70}")

        resp = session.get(f"{FOLIO_BASE}/{resid}", timeout=30)
        print(f"  HTTP {resp.status_code}, {len(resp.text)} bytes")
        if resp.status_code != 200:
            continue

        (OUT_DIR / f"folio_{resid}.html").write_text(resp.text, encoding="utf-8")

        dump_table_headers(resp.text)

        folio = parse_folio(resp.text, resid)
        print(f"\n  services:     {len(folio['services'])}")
        for svc in folio["services"][:4]:
            print(f"    {svc}")

        print(f"  payments:     {len(folio['payments'])}")
        for pmt in folio["payments"][:4]:
            print(f"    {pmt}")

        print(f"  room_charges: {len(folio['room_charges'])}")
        for chg in folio["room_charges"][:4]:
            print(f"    {chg}")

        # El importe pagado debería cuadrar con la suma de la tabla de pagos.
        paid = sum(
            (p["amount"] for p in folio["payments"] if p["amount"]),
            Decimal("0"),
        )
        charged = sum(
            (s["amount"] for s in folio["services"] if s["amount"]),
            Decimal("0"),
        )
        charged += sum(
            (c["amount"] for c in folio["room_charges"] if c["amount"]),
            Decimal("0"),
        )
        print(f"\n  suma pagos     = {paid}")
        print(f"  suma cargos    = {charged}")
        print(f"  diferencia     = {charged - paid}  (lo que le queda al hotel)")


if __name__ == "__main__":
    main()
