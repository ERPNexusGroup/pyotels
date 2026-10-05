"""El "mover reserva" = POST /reservation_c2/update_reservation (sólo lectura).

Lo que se busca aquí es el contrato del cambio de habitación / fechas:

- El paso 1 de los dos asistentes postea a `/reservation_c2/update_reservation`
  con `reservation_id`, `room_id`, `category`, `datein`, `dateout`...
- La pestaña del check-out se titula literalmente "Cambiar las fechas de la
  estancia", o sea que ese form es la operación de mover.

**No se envía el form.** Se vuelca su estructura y las opciones de los
select para poder escribir el cliente contra algo leído.

    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_move_update_reservation.py [resid]
"""
import sys
import urllib3
from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

urllib3.disable_warnings()

BASE = "https://desktop.otelms.com"
HOTEL = "18330"
RESID = sys.argv[1] if len(sys.argv) > 1 else "23565"
if not RESID.isdigit():
    raise SystemExit(f"el resid tiene que ser numérico, no {RESID!r}")

session = CalendarSyncService._login(get_settings(), HOTEL)

PAGES = [
    ("check-in  paso 1", f"{BASE}/master_c2/step_1/{RESID}/?landing_page=folio"),
    ("check-out paso 1", f"{BASE}/master_c2/checkout_step_1/{RESID}?landing_page=folio"),
]

for label, url in PAGES:
    print("\n" + "#" * 78)
    print(f"# {label}  {url}")
    print("#" * 78)
    resp = session.get(url, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("status:", resp.status_code)

    form = soup.find("form", {"action": "/reservation_c2/update_reservation"})
    if form is None:
        print("  NO hay form update_reservation en esta página")
        continue

    print(f"\n  action={form.get('action')!r} method={form.get('method')!r} "
          f"id={form.get('id')!r}")
    print(f"  campos: {len(form.find_all(['input','select','textarea','button']))}")

    print("\n  -- campos que importan (con selected):")
    for field in form.find_all(["input", "select", "textarea"]):
        name = field.get("name")
        if not name:
            continue
        if field.name == "select":
            options = field.find_all("option")
            sel = [o.get("value") for o in options if o.has_attr("selected")]
            vals = [(o.get("value"), o.get_text(strip=True)[:24]) for o in options[:6]]
            print(f"    select {name!r}: {len(options)} opciones, "
                  f"selected={sel}, muestra={vals}")
        elif field.name == "textarea":
            print(f"    textarea {name!r}: {field.get_text(strip=True)[:50]!r}")
        else:
            print(f"    input {name!r} type={field.get('type')!r} "
                  f"value={(field.get('value') or '')[:40]!r}"
                  f"{' CHECKED' if field.has_attr('checked') else ''}")

    print("\n  -- day_price[] (muestra):")
    day_prices = [f for f in form.find_all("input")
                  if (f.get("name") or "").startswith("day_price")]
    print(f"     {len(day_prices)} campos day_price[day_id]; "
          f"primeros: {[(f['name'], f.get('value')) for f in day_prices[:3]]}")

    print("\n  -- botones del form:")
    for b in form.find_all(["button", "input"]):
        if b.get("type") in ("submit", "button", "reset"):
            print(f"    <{b.name}> name={b.get('name')!r} value={b.get('value')!r} "
                  f"text={b.get_text(strip=True)[:40]!r} class={b.get('class')!r}")

    print("\n  -- JS que postea este form:")
    text = resp.text
    for marker in ("frmdata_modal", "update_reservation"):
        idx = text.find(marker)
        while idx != -1:
            snippet = text[max(0, idx - 350):idx + 350]
            if "ajax" in snippet or "post" in snippet.lower() or "submit" in snippet.lower():
                print(f"    [{marker}] ...{snippet}...".replace("\n", " ")[:700])
                print()
            idx = text.find(marker, idx + 1)
