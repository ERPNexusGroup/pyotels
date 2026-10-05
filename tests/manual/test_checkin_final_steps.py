"""Recorrer los pasos finales del check-in / check-out (sólo lectura).

El paso 1 de ambos asistentes ya se leyó en `test_checkin_wizard.py`. Aquí
van los que hacen el trabajo real:

    check-in : step_1 → step_2 → step_3 → step_4  ("Check-in")
    check-out: checkout_step_1 → _step_2 → _step_3 ("Factura final")

Objetivo: encontrar el POST que confirma, sus campos obligatorios y qué
indica que la operación se hizo. **No se envía nada** — un check-in real
mueve una estancia con huéspedes dentro.

    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_checkin_final_steps.py [resid]
"""
import re
import sys
import urllib3
from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

urllib3.disable_warnings()

BASE = "https://desktop.otelms.com"
HOTEL = "18330"
RESID = sys.argv[1] if len(sys.argv) > 1 else "23356"
if not RESID.isdigit():
    raise SystemExit(f"el resid tiene que ser numérico, no {RESID!r}")

session = CalendarSyncService._login(get_settings(), HOTEL)

PATHS = [
    f"/master_c2/step_2/{RESID}",
    f"/master_c2/step_3/{RESID}",
    f"/master_c2/step_4/{RESID}",
    f"/master_c2/checkout_step_2/{RESID}",
    f"/master_c2/checkout_step_3/{RESID}",
]


def dump(path: str) -> None:
    url = f"{BASE}{path}"
    print("\n" + "#" * 78)
    print("# GET", url)
    print("#" * 78)
    resp = session.get(url, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("status:", resp.status_code, "| title:", soup.title.get_text(strip=True) if soup.title else "-")

    text = soup.get_text(" ", strip=True)
    print("\n-- primeros 400 chars de texto:")
    print("   ", text[:400].replace("\n", " "))

    print("\n-- forms con action:")
    for form in soup.find_all("form"):
        print(f"   action={form.get('action')!r} method={form.get('method')!r} "
              f"id={form.get('id')!r}")
        named = [f for f in form.find_all(["input", "select", "textarea", "button"])
                 if f.get("name")]
        print(f"   campos con name: {len(named)}")
        for field in named[:40]:
            opts = ""
            if field.name == "select":
                opts = " opciones=" + str([o.get_text(strip=True)[:20] for o in field.find_all("option")][:8])
            print(f"      {field.name:<9} name={field.get('name')!r} "
                  f"type={field.get('type')!r} value={(field.get('value') or '')[:50]!r}"
                  f"{opts}")
        submits = [f for f in form.find_all(["button", "input"])
                   if f.get("type") in ("submit", "button") or f.name == "button"]
        for s in submits:
            print(f"      BOTON name={s.get('name')!r} value={s.get('value')!r} "
                  f"text={s.get_text(strip=True)[:40]!r} "
                  f"onclick={(s.get('onclick') or '')[:100]!r}")

    print("\n-- onclick que mencionan confirmación/guardado:")
    for node in soup.find_all(attrs={"onclick": True}):
        onclick = node["onclick"]
        if re.search(r"confirm|save|submit|ajax|post|checkin|checkout|\$\.post|form\.submit",
                     onclick, re.I):
            print(f"   <{node.name}> id={node.get('id')!r} class={node.get('class')!r}")
            print(f"      text   ={node.get_text(strip=True)[:60]!r}")
            print(f"      onclick={onclick[:260]!r}")

    print("\n-- funciones JS de submit/confirm:")
    for m in re.finditer(r"function\s+(\w+)\s*\([^)]*\)\s*\{", resp.text):
        name = m.group(1)
        if not re.search(r"save|submit|confirm|check|final|do_", name, re.I):
            continue
        body = resp.text[m.start():m.start() + 700]
        print(f"\n   function {name}():")
        for line in body.splitlines()[:20]:
            print(f"       {line.strip()[:170]}")

    print("\n-- URLs de POST/ajax:")
    for u in sorted(set(re.findall(r"['\"]([^'\"]*(?:ajax|save|final|confirm)[^'\"]*)['\"]",
                                   resp.text, re.I)))[:20]:
        print(f"   {u}")


for path in PATHS:
    dump(path)
