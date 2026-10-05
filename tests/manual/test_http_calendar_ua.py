"""Diagnóstico: por qué el sync HTTP del worker dice 'Sesión no válida'.

El sync del worker falla con:

    HTTP calendar falló, probando browser
    error='Sesión no válida tras login (redirect a login)'

Hay dos caminos de login HTTP en el repo y se comportan distinto:

  - `http_calendar.fetch_calendar_html` (el que usa el sync): manda
    `User-Agent: pyotels/1.0`.
  - `CalendarSyncService._login` (el que funciona desde Windows): manda
    `settings.browser_user_agent`.

Este script corre los dos contra el portal real y compara, para confirmar si
el portal rechaza el User-Agent de bot. No replica el cliente HTTP: usa las
dos funciones de producción tal cual.

Uso:
    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_http_calendar_ua.py
"""
import asyncio
import sys

from otelms.config.constants import OtelMSUrls
from otelms.config.settings import get_settings
from otelms.scraping.http_calendar import fetch_calendar_html
from otelms.services.calendar_sync_service import CalendarSyncService

HOTEL_ID = "18330"


async def via_http_calendar() -> tuple[bool, str]:
    """El camino que usa el sync: User-Agent pyotels/1.0."""
    settings = get_settings()
    urls = OtelMSUrls(settings.otelms_base_domain, HOTEL_ID)
    try:
        html = await fetch_calendar_html(
            hotel_id=HOTEL_ID,
            username=settings.otelms_default_username,
            password=settings.otelms_default_password,
            base_domain=settings.otelms_base_domain,
        )
    except Exception as exc:  # noqa: BLE001 - diagnóstico: queremos el motivo
        return False, f"{type(exc).__name__}: {exc}"
    ok = "reservation_c2/calendar" in html
    return ok, f"calendar_url={urls.calendar_url(None)} bytes={len(html)}"


def via_calendar_sync() -> tuple[bool, str]:
    """El camino que funciona: User-Agent de browser de settings."""
    settings = get_settings()
    try:
        session = CalendarSyncService._login(settings, HOTEL_ID)
    except Exception as exc:  # noqa: BLE001 - diagnóstico: queremos el motivo
        return False, f"{type(exc).__name__}: {exc}"
    resp = session.get(
        "https://desktop.otelms.com/reservation_c2/calendar", timeout=30
    )
    ok = "reservation_c2/calendar" in resp.text
    return ok, f"status={resp.status_code} bytes={len(resp.text)}"


def main() -> int:
    settings = get_settings()
    print(f"base_domain={settings.otelms_base_domain!r}")
    print(f"browser_ua  ={settings.browser_user_agent[:70]}\n")

    ok1, detail1 = asyncio.run(via_http_calendar())
    print(f"{'OK   ' if ok1 else 'FALLA'} http_calendar.fetch_calendar_html  (UA pyotels/1.0)")
    print(f"        {detail1}\n")

    ok2, detail2 = via_calendar_sync()
    print(f"{'OK   ' if ok2 else 'FALLA'} CalendarSyncService._login        (UA browser)")
    print(f"        {detail2}\n")

    if ok1 and ok2:
        print("=> Ambos funcionan: el fallo del worker es específico del contenedor.")
    elif ok2 and not ok1:
        print("=> Confirmado: el portal rechaza el User-Agent pyotels/1.0.")
    else:
        print("=> Ninguno funciona desde aquí: revisar sesión/2FA antes que el UA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())