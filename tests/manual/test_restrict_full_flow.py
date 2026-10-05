"""Round-trip con la secuencia completa de la UI, no sólo el guardado.

`test_restrict_save_roundtrip.py` hizo POST a `save_restricts` tal cual y la
respuesta fue `ok:1` pero `count_restricts_data:0`: el portal aceptó la llamada
y no aplicó nada. La celda quedó idéntica antes y después.

La secuencia real del JS es de tres pasos:

1. Arrastrar sobre la rejilla → al soltar, POST
   `/reservation_c2/ajax_calendar_restricts` con `resstrict_data[N][...]`.
   El servidor guarda la selección y devuelve el modal.
2. Editar el modal (fechas, `closed`, mínimos).
3. "Guardar" → POST `/reservation_c2/save_restricts` con el form serializado.

Este script hace los tres, en ese orden, y relee la rejilla después de cada
escritura. Misma celda inocua que el otro script: categoría 21 (Overbooking),
tarifa 1, 2026-11-19. El `finally` reabre.

Otra diferencia que se prueba aquí: si el paso 1 se repite con la MISMA celda
varias veces, la selección se acumula o se replace.
"""
import json
from pathlib import Path

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.services.calendar_sync_service import CalendarSyncService

BASE = "https://desktop.otelms.com"
CATEGORY = "21"
RATE = "1"
DAY = "2026-11-19"
out_dir = Path(__file__).parent

client = CalendarSyncService._login(get_settings(), "18330")


def read_cell(tag: str) -> str:
    """Relectura de la celda en la rejilla."""
    page = client.get(f"{BASE}/reservation_c2/restrict_calendar", timeout=30)
    soup = BeautifulSoup(page.text, "html.parser")
    rows = [
        td for td in soup.select(f'td[category_id="{CATEGORY}"]')
        if td.get("rate_id") == RATE and td.get("fulldate") == DAY
    ]
    if not rows:
        print(f"[{tag}] celda no encontrada")
        return ""
    html = str(rows[0])
    print(f"[{tag}] clases={sorted(rows[0].get('class', []))}")
    print(f"[{tag}] {html[:260]}")
    return html


def select_cells(cells: list[dict[str, str]], tag: str) -> str:
    """Paso 1: la selección que hace el arrastre de la UI."""
    payload: dict[str, str] = {}
    for idx, cell in enumerate(cells):
        for key, value in cell.items():
            payload[f"resstrict_data[{idx}][{key}]"] = value
    resp = client.post(
        f"{BASE}/reservation_c2/ajax_calendar_restricts",
        data=payload,
        headers={
            "Referer": f"{BASE}/reservation_c2/restrict_calendar",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    print(f"[sel:{tag}] HTTP {resp.status_code}, {len(resp.text)} bytes")
    # ¿El modal devuelto trae `closed` ya puesto por el servidor?
    soup = BeautifulSoup(resp.text, "html.parser")
    for sel in soup.select("select[name='closed']"):
        chosen = sel.find("option", selected=True)
        print(f"[sel:{tag}] select closed -> elegido={chosen.get_text(strip=True) if chosen else None}")
    Path(out_dir / f"restrict_modal_{tag}.html").write_text(resp.text, encoding="utf-8")
    return resp.text


def save(closed: str, tag: str, modal_html: str | None = None) -> dict:
    """Paso 3: Guardar. Serializa el modal si se tiene, si no el payload fijo."""
    if modal_html:
        soup = BeautifulSoup(modal_html, "html.parser")
        form = soup.find("form")
        payload = {}
        for el in form.find_all(["input", "select"]):
            name = el.get("name")
            if not name or el.get("type") == "checkbox" and not el.has_attr("checked"):
                continue
            if el.name == "select":
                opt = el.find("option", selected=True) or el.find("option")
                payload[name] = opt.get("value", "")
            else:
                payload[name] = el.get("value", "")
        payload["closed"] = closed
    else:
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
    print(f"[save:{tag}] payload={payload}")
    print(f"[save:{tag}] HTTP {resp.status_code} -> {resp.text[:300]}")
    try:
        return json.loads(resp.text)
    except ValueError:
        return {"_raw": resp.text[:300]}


before = read_cell("inicial")
print()

cell = {"rate_id": RATE, "date": "20776", "fulldate": DAY, "category_id": CATEGORY}

try:
    modal = select_cells([cell], "cerrar")
    close_res = save("1", "cerrar", modal_html=modal)
    Path(out_dir / "restrict_close_full.json").write_text(
        json.dumps(close_res, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print()
    after_close = read_cell("cerrada")
finally:
    print()
    modal2 = select_cells([cell], "abrir")
    open_res = save("0", "abrir", modal_html=modal2)
    Path(out_dir / "restrict_open_full.json").write_text(
        json.dumps(open_res, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print()
    after_open = read_cell("reabierta")

print("\n=== VEREDICTO ===")
print(f"count al cerrar : {close_res.get('count_restricts_data')} restricts_data={close_res.get('restricts_data')}")
print(f"count al abrir  : {open_res.get('count_restricts_data')} restricts_data={open_res.get('restricts_data')}")
print("cambió al cerrar? ", before != after_close)
print("volvió al inicial?", before == after_open)