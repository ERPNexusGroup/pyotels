"""Descubrir el flujo de check-in / check-out de OtelMS (sólo lectura).

En el folio hay dos botones que ya se(localizaron):

    #do_checkin   -> /master_c2/step_1/{resid}/?landing_page=folio
    #do_checkout  -> /master_c2/checkout_step_1/{resid}?landing_page=folio

Son wizards de varios pasos. Este script **sólo hace GET**: recorre las
páginas del asistente y vuelca forms, campos, action y JS, para escribir
después el código contra algo leído y no inventado.

NO se envía ningún formulario. Un check-in real cambia el estado de una
estancia de verdad con huéspedes dentro.

    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_checkin_wizard.py
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
# 23356 está checked-in (in-house), así que su paso 1 de check-in debería
# estar bloqueado. Sirve justamente para ver cómo marca OtelMS "ya hecho".
RESID = sys.argv[1] if len(sys.argv) > 1 else "23356"

# Los dos asistentes, en el orden en que los recorre el portal.
PATHS = (
    f"/master_c2/step_1/{RESID}/?landing_page=folio",
    f"/master_c2/checkout_step_1/{RESID}?landing_page=folio",
)

session = CalendarSyncService._login(get_settings(), HOTEL)


def dump_page(path: str) -> BeautifulSoup:
    """Vuelca una página del portal.

    Recibe un **path**, no una URL: el host se fija aquí dentro. Así ningún
    argumento puede llevar a otro sitio, y `RESID` además se valida como
    numérico antes de interpolarse.
    """
    url = f"{BASE}{path}"
    print("\n" + "#" * 78)
    print("# GET", url)
    print("#" * 78)
    resp = session.get(url, timeout=30)
    print("status:", resp.status_code, "| bytes:", len(resp.text))
    soup = BeautifulSoup(resp.text, "html.parser")

    print("\n-- <title>:", soup.title.get_text(strip=True) if soup.title else "(none)")

    # ¿Hay un mensaje de "ya está checked in" o similar?
    body_text = soup.get_text(" ", strip=True)
    for kw in ("ya realiz", "ya ha", "checked in", "Check In", "no se puede",
               "residente", "ya esta", "ya está"):
        if kw.lower() in body_text.lower():
            idx = body_text.lower().find(kw.lower())
            print(f"  [aviso '{kw}'] ...{body_text[max(0, idx - 120):idx + 160]}...")

    print("\n-- forms:")
    for form in soup.find_all("form"):
        print(f"  action={form.get('action')!r} method={form.get('method')!r} "
              f"id={form.get('id')!r} enctype={form.get('enctype')!r}")
        for field in form.find_all(["input", "select", "textarea", "button"]):
            name = field.get("name")
            if not name:
                continue
            print(f"      {field.name:<9} name={name!r} type={field.get('type')!r} "
                  f"value={(field.get('value') or '')[:60]!r}")

    print("\n-- inputs hidden relevantes:")
    for node in soup.select("input[type=hidden]"):
        name = node.get("name") or ""
        if re.search(r"resid|hotel|token|csrf|step|action|flag|date", name, re.I):
            print(f"   {name} = {(node.get('value') or '')[:80]!r}")

    print("\n-- botones/enlaces con onclick o href de acción:")
    seen = set()
    for node in soup.find_all(["a", "button", "input"]):
        onclick = node.get("onclick") or ""
        href = node.get("href") or ""
        blob = f"{onclick} {href}"
        if not re.search(r"master_c2|checkin|checkout|step_|save|confirm|next|submit",
                         blob, re.I):
            continue
        line = (node.get_text(strip=True)[:40], onclick[:150], href[:150],
                node.get("id") or "", node.get("class") or "")
        if line in seen:
            continue
        seen.add(line)
        print(f"   <{node.name}> id={line[3]!r} class={line[4]!r}")
        print(f"       text  ={line[0]!r}")
        print(f"       onclick={line[1]!r}")
        print(f"       href   ={line[2]!r}")

    print("\n-- submits y funciones de JS:")
    for m in re.finditer(r"function\s+(\w+)\s*\(", resp.text):
        name = m.group(1)
        if re.search(r"check|save|next|step|submit|confirm|save_|do_", name, re.I):
            snippet = resp.text[m.start():m.start() + 500]
            print(f"\n   function {name}():")
            for line in snippet.splitlines()[:18]:
                print(f"       {line.strip()[:160]}")

    print("\n-- referencias a master_c2 / ajax en el JS:")
    urls = set(re.findall(r"['\"](/?[a-z_0-9/]*(?:master_c2|ajax|save|check)[a-z_0-9/]*)['\"]",
                          resp.text, re.I))
    for u in sorted(urls)[:25]:
        print(f"   {u}")

    return soup


if not RESID.isdigit():
    raise SystemExit(f"el resid tiene que ser numérico, no {RESID!r}")

print(f"Reserva explorada: {RESID}")
for _path in PATHS:
    dump_page(_path)
