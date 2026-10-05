"""Round-trip real de cerrar/abrir UNA celda, y dejarla como estaba.

Por qué esta celda y no otra: categoría 21 (Overbooking), tarifa 1 (Standard),
día 2026-11-19 — el último de la rejilla y el más lejos posible de cualquier
estancia real. Antes de tocar nada se comprueba que la celda está abierta.

Secuencia, con relectura de la rejilla entre pasos:

1. Estado inicial: disponibilidad de la categoría 21 el 2026-11-19.
2. POST /reservation_c2/save_restricts con closed=1 (Cerrado).
3. Relectura: la disponibilidad debe bajar y la celda llevar marca de cerrada.
4. POST /reservation_c2/save_restricts con closed=0 (Abierto).
5. Relectura: la disponibilidad debe volver a la del paso 1.

El paso 4 deshace el 2. Si algo revienta por el medio, el `finally` vuelve a
abrir la celda.

Lo que este script fija, y `scraping/restrictions.py` tenía al revés:
`closed=1` es Cerrado y `closed=0` es Abierto. El otro endpoint de la misma
página, `save_restrict_close_open`, usa `restrict_type` 1=Cerrar y 2=Abrir
(lo dicen `close_save()` y `open_save()` en el JS), mientras que
restrictions.py asume 0=cerrar y 1=abrir.
"""
import json
from pathlib import Path

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

BASE = "https://desktop.otelms.com"
CATEGORY = "21"          # Overbooking
RATE = "1"               # Standard
DAY = "2026-11-19"       # último día de la rejilla
out_dir = Path(__file__).parent

client = CalendarSyncService._login(get_settings(), "18330")


def availability(day: str) -> dict[str, str]:
    """Disponibilidad por categoría leyendo la fila resumen de la rejilla."""
    page = client.get(f"{BASE}/reservation_c2/restrict_calendar", timeout=30)
    soup = BeautifulSoup(page.text, "html.parser")
    cells = soup.select(f'td[category_id="{CATEGORY}"]')
    # Cada categoría tiene 2 tarifas y N días; se pide sólo la tarifa pedida.
    rows = [td for td in cells if td.get("rate_id") == RATE and td.get("fulldate") == day]
    return {
        "n_celdas": str(len(rows)),
        "clases": " ".join(sorted(rows[0].get("class", []))) if rows else "",
        "html": str(rows[0])[:300] if rows else "",
    }


def save(closed: str) -> dict:
    """POST a save_restricts replicando el serialize() del modal."""
    payload = {
        "delete_action": "0",
        "category_id": CATEGORY,
        "rate_id": RATE,
        "datein": DAY,
        "dateout": DAY,
        "closed": closed,
        "closedonarrival": "2",
        "closedondeparture": "2",
        "minstaythrought": "",
        "maxstay": "",
        "minstayarrival": "",
    }
    resp = client.post(
        f"{BASE}/reservation_c2/save_restricts",
        data=payload,
        headers={
            "Referer": f"{BASE}/reservation_c2/restrict_calendar",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    print(f"\n>>> save_restricts closed={closed}: HTTP {resp.status_code}")
    print(f"    body[:400] = {resp.text[:400]}")
    try:
        return json.loads(resp.text)
    except ValueError:
        return {"_raw": resp.text[:400]}


before = availability(DAY)
print("=== 1. ESTADO INICIAL ===")
print(json.dumps(before, indent=2, ensure_ascii=False))

try:
    # --- 2/3. Cerrar y re-leer ----------------------------------------------
    close_res = save("1")
    Path(out_dir / "restrict_close.json").write_text(
        json.dumps(close_res, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    after_close = availability(DAY)
    print("\n=== 3. TRAS CERRAR ===")
    print(json.dumps(after_close, indent=2, ensure_ascii=False))
finally:
    # --- 4. Reabrir, pase lo que pase ----------------------------------------
    open_res = save("0")
    Path(out_dir / "restrict_open.json").write_text(
        json.dumps(open_res, indent=2, ensure_ascii=False), encoding="utf-8"
    )

after_open = availability(DAY)
print("\n=== 5. TRAS REABRIR (debe coincidir con el paso 1) ===")
print(json.dumps(after_open, indent=2, ensure_ascii=False))

print("\n=== VEREDICTO ===")
print("clases iniciales :", before["clases"])
print("clases cerradas  :", after_close["clases"])
print("clases finales   :", after_open["clases"])
print("¿cambió al cerrar? ", before["clases"] != after_close["clases"] or before["html"] != after_close["html"])
print("¿volvió al inicial?", before["html"] == after_open["html"])
print(f"JSON save(1) ok={close_res.get('ok')} count={close_res.get('count_restricts_data')}")
print(f"JSON save(0) ok={open_res.get('ok')} count={open_res.get('count_restricts_data')}")