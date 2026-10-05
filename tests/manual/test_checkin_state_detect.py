"""¿Se puede saber si una reserva está checked-in sin llamar a set_checkin?

El campo "Estado" del folio ya se demostró poco fiable (la Tarea 1.4). Pero en
el folio los botones traen clases:

    <span class="withtoggle"      ... #do_checkin>
    <span class="withtoggle d0"   ... #do_checkout>

La hipótesis es que `d0` marca una acción deshabilitada. Si se cumple, sirve
como detector de estado **de sólo lectura**: no hay que ejecutar un check-out
para averiguar si ya se hizo.

Se comprueba contra una reserva que sí está dentro (23356) y otra pendiente
de llegar (23565).

    env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_checkin_state_detect.py
"""
import re
import urllib3
from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

urllib3.disable_warnings()

BASE = "https://desktop.otelms.com"
HOTEL = "18330"

# (resid, lo que sabemos de él)
CASOS = [
    ("23356", "in-house desde 2026-09-20 (check-in ya hecho)"),
    ("23565", "pendiente, llega 2026-10-09 (nunca checked-in)"),
    ("23552", "la lista lo marcaba 'Check i...'"),
    ("23558", "la lista lo marcaba 'Check in'"),
]

session = CalendarSyncService._login(get_settings(), HOTEL)

print(f"{'resid':<8}{'checkin':<34}{'checkout':<34}estado folio")
print("-" * 110)

for resid, nota in CASOS:
    resp = session.get(f"{BASE}/reservation_c2/folio/{resid}", timeout=30)
    if resp.status_code != 200:
        print(f"{resid:<8}HTTP {resp.status_code}")
        continue
    soup = BeautifulSoup(resp.text, "html.parser")

    def clase(anchor_id: str) -> str:
        node = soup.find(id=anchor_id)
        if node is None:
            return "(no existe)"
        # la clase cuelga del <span> contenedor
        holder = node.find_parent(class_=re.compile(r"withtoggle"))
        return " ".join(holder.get("class")) if holder else "(sin span)"

    checkin, checkout = clase("do_checkin"), clase("do_checkout")

    estado = "(no encontrado)"
    body = soup.get_text(" ", strip=True)
    for cand in ("Check out", "Check in", "Cancelada", "Reservación", "No show"):
        if cand in body:
            estado = cand
            break

    print(f"{resid:<8}{checkin:<34}{checkout:<34}{estado}")
    print(f"{'':<8}└─ {nota}")
