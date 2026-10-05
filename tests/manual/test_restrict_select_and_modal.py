"""Localiza el POST que ejecuta el cierre/apertura de fechas.

Lo que se sabe leyendo `restrict_calendar.html` (lo produce `test_restrict_calendar.py`):

- El form `#send_restricts_close_open` hace POST a
  `/reservation_c2/save_restrict_close_open` y lleva SOLO dos campos:
  `restrict_type` y `date` (el rango del daterangepicker, "YYYY-MM-DD - YYYY-MM-DD").
  No lleva categorías.
- El JS de la página pone `restrict_type = 1` en `close_save()` y
  `restrict_type = 2` en `open_save()`. Es lo contrario de lo que asume
  `scraping/restrictions.py` (0 = cerrar, 1 = abrir), que cerraría fechas al
  pedir abrirlas.
- Las categorías no viajan en ese POST: se eligen arrastrando sobre la rejilla
  (jQuery UI selectable). Al soltar, cada `td.calendar_td.ui-selected` aporta
  rate_id/date/fulldate/category_id y se mandan a
  `/reservation_c2/ajax_calendar_restricts` como `resstrict_data` (con tres "s").
  Ese endpoint devuelve un modal, que es donde debería estar el guardado real.

Este script reproduce la selección por HTTP (sin browser) y vuelca ese modal.

Usa el login de producción (`CalendarSyncService._login`) porque
`get_authenticated_http_session` falla contra este portal: comprueba
`"login" in resp.url.path`, pero OtelMS no redirige, contesta 200 con un
meta-refresh a /reservation_c2/calendar, así que la URL final sigue siendo
/login_c2/do_single_login y la función lanza siempre.

No escribe nada en el calendario: sólo pide el modal de confirmación.
"""
import re
from pathlib import Path

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

BASE = "https://desktop.otelms.com"
out_dir = Path(__file__).parent

client = CalendarSyncService._login(get_settings(), "18330")

# --- 1. La rejilla y sus celdas seleccionables -------------------------------
page = client.get(f"{BASE}/reservation_c2/restrict_calendar", timeout=30)
soup = BeautifulSoup(page.text, "html.parser")
cells = soup.select("td.calendar_td.ui-selectee")
print(f"Celdas seleccionables: {len(cells)}")
print(f"rate_ids: {sorted({c.get('rate_id') for c in cells})}")
print(f"category_ids: {sorted({c.get('category_id') for c in cells})}")

# Celda más lejana del grid: es la selección menos capaz de afectar a una
# reserva real, y abre el modal igual que cualquier otra.
target = max(cells, key=lambda c: c.get("fulldate", ""))
print(f"\nCelda objetivo: {target.get('title')} -> {dict(target.attrs)}")

selection = [{
    "rate_id": target.get("rate_id"),
    "date": target.get("date"),
    "fulldate": target.get("fulldate"),
    "category_id": target.get("category_id"),
}]

# jQuery `data: ({resstrict_data: data})` con data = array de objetos serializa
# claves indexadas: resstrict_data[0][rate_id]=...
payload: dict[str, str] = {}
for idx, cell in enumerate(selection):
    for key, value in cell.items():
        payload[f"resstrict_data[{idx}][{key}]"] = value
print(f"\nPayload: {payload}")

resp = client.post(
    f"{BASE}/reservation_c2/ajax_calendar_restricts",
    data=payload,
    headers={
        "Referer": f"{BASE}/reservation_c2/restrict_calendar",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"\najax_calendar_restricts: {resp.status_code}, {len(resp.text)} bytes")
out_dir.joinpath("restrict_modal.html").write_text(resp.text, encoding="utf-8")

modal = BeautifulSoup(resp.text, "html.parser")

print("\n--- forms del modal ---")
for form in modal.find_all("form"):
    print(f"  id={form.get('id')} method={form.get('method')} action={form.get('action')}")
    for el in form.find_all(["input", "select", "textarea", "button"]):
        attrs = {k: v for k, v in el.attrs.items() if k in ("name", "type", "value", "id")}
        if el.name == "select":
            attrs["options"] = [(o.get("value"), o.get_text(strip=True)) for o in el.find_all("option")]
        print(f"    {el.name} {attrs}")

print("\n--- botones/enlaces del modal ---")
for btn in modal.find_all(["button", "a"]):
    text = btn.get_text(strip=True)
    onclick = btn.get("onclick", "")
    if text or onclick:
        print(f"  '{text}' onclick={onclick[:80]}")

print("\n--- URLs citadas en el modal ---")
print(sorted(set(re.findall(r"url\s*:\s*['\"]([^'\"]+)", resp.text))))
print(sorted(set(re.findall(r"/reservation_c2/[a-z_]+", resp.text))))

print("\n--- texto del modal (primeros 1500 chars) ---")
print(modal.get_text(" ", strip=True)[:1500])