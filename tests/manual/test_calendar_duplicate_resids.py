"""Diagnóstico: ¿por qué el sync reporta 49 reservas y solo quedan 7 filas?

El sync_logs dice `records_processed=49, records_created=49, error_count=0`
pero la tabla `reservations` tiene 7 filas. Dos hipótesis:

  A) El parser emite una entrada por celda del calendario (una reserva de N
     noches aparece N veces), así que 49 entradas son 7 reservas distintas.
  B) El upsert falla en silencio y las filas nunca llegan a commitearse.

Este script solo lee: no escribe nada en la BD. Reusa el login HTTP de
`CalendarSyncService._login`, que es el mismo que usa producción.

Uso:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_calendar_duplicate_resids.py
"""
import collections
import sys
from pathlib import Path

from otelms.config.settings import get_settings
from otelms.scraping.calendar_extract import extract_reservations_from_calendar
from otelms.services.calendar_sync_service import CalendarSyncService

HOTEL_ID = "18330"
CALENDAR_URL = "https://desktop.otelms.com/reservation_c2/calendar"


def dump_calendar() -> str:
    """Login con el mismo _login que usa el sync de producción."""
    session = CalendarSyncService._login(get_settings(), HOTEL_ID)
    resp = session.get(CALENDAR_URL, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(f"Calendar HTTP {resp.status_code}")
    return resp.text


def report(html: str) -> int:
    out_dir = Path(__file__).parent
    out_dir.joinpath("calendar_dump_sync.html").write_text(html, encoding="utf-8")
    print(f"HTML del calendar: {len(html)} bytes -> calendar_dump_sync.html")

    reservations = extract_reservations_from_calendar(html)
    total = len(reservations)
    by_resid: dict[str, list[dict]] = collections.defaultdict(list)
    for res in reservations:
        by_resid[str(res.get("resid"))].append(res)
    distinct = len(by_resid)
    dupes = {k: v for k, v in by_resid.items() if len(v) > 1}

    print(f"\nEntradas parseadas : {total}")
    print(f"resid distintos    : {distinct}")
    print(f"resid repetidos    : {len(dupes)}")

    if total == distinct:
        print("\n=> Sin duplicados por resid: el problema NO es el parser.")
        return 1

    print("\nDetalle (resid -> apariciones, fechas derivadas):")
    for resid, entries in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
        print(f"  {resid}: {len(entries)}x")
        for combo in sorted({
            (str(e.get("check_in"))[:10], str(e.get("check_out"))[:10], str(e.get("room_number")))
            for e in entries
        }):
            print(f"      check_in={combo[0]}  check_out={combo[1]}  room={combo[2]!r}")

    sample = next(iter(dupes.values()))
    print(f"\nCampos de una entrada: {sorted({k for e in sample for k in e})}")
    print("¿Las copias del mismo resid coinciden en todos los campos? (* = difieren)")
    for key in sorted({k for e in sample for k in e}):
        values = {str(e.get(key)) for e in sample}
        print(f"  {'  ' if len(values) == 1 else '* '}{key}: {sorted(values)}")

    return 0


def main() -> int:
    return report(dump_calendar())


if __name__ == "__main__":
    sys.exit(main())