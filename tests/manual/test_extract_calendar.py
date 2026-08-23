"""Extrae reservas del calendar y las guarda en BD."""
import re
import json
import requests
import urllib3
from bs4 import BeautifulSoup
from otelms.config.settings import get_settings

urllib3.disable_warnings()

settings = get_settings()
session = requests.Session()
session.headers.update({
    "User-Agent": settings.browser_user_agent,
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
})
session.verify = False

# Login
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
resp = session.post(
    "https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel": "18330", "login": settings.otelms_default_username,
          "password": settings.otelms_default_password, "action": "login"},
    headers={"Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
             "Origin": "https://desktop.otelms.com"},
    timeout=15,
)
print(f"Login: {resp.status_code}")

# Descargar calendar completo
cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
print(f"Calendar: {len(cal.text)} bytes")

# Guardar HTML bruto para análisis
with open("calendario_debug.html", "w", encoding="utf-8") as f:
    f.write(cal.text)

soup = BeautifulSoup(cal.text, "html.parser")

# Identificar todos los enlaces a reservas (folio, edit)
folio_links = soup.find_all("a", href=re.compile(r"/reservation_c2/folio/"))
edit_links = soup.find_all("a", href=re.compile(r"/reservation_c2/edit/"))
guest_links = soup.find_all("a", href=re.compile(r"/reservation_c2/guestfolio/"))

print(f"\n📊 Encontrados: {len(folio_links)} folios, {len(edit_links)} edits, {len(guest_links)} guestfolios")

# Extraer IDs únicos
folio_ids = set()
res_ids = set()
for link in folio_links:
    match = re.search(r"/folio/(\d+)/", link["href"])
    if match:
        folio_ids.add(match.group(1))
    match = re.search(r"resid[=\s\"]+(\d+)", str(link.attrs))
    if match:
        res_ids.add(match.group(1))

edit_ids = set()
for link in edit_links:
    match = re.search(r"/edit/(\d+)", link["href"])
    if match:
        edit_ids.add(match.group(1))

print(f"IDs únicos: folios={len(folio_ids)}, resid={len(res_ids)}, edit={len(edit_ids)}")
print(f"Ejemplos folio_ids: {sorted(list(folio_ids))[:5]}")
print(f"Ejemplos edit_ids: {sorted(list(edit_ids))[:5]}")

# Extraer tooltips de celdas
tooltips = soup.find_all("div", class_=re.compile(r"tooltip", re.I))
print(f"\nTooltips: {len(tooltips)}")
if tooltips:
    print(f"Tooltip sample: {tooltips[0].get_text()[:100]}")

# Extraer tooltips inline (title attributes en links)
res_items = soup.find_all(attrs={"resid": True})
print(f"Res items (resid attr): {len(res_items)}")

# Analizar estructura de una celda
cells = soup.find_all("td", class_=re.compile(r"calendar_cell", re.I))
print(f"\nCeldas de calendario: {len(cells)}")
if cells:
    # Muestra clases de una celda
    cell_classes = cells[0].get("class", [])
    print(f"Ejemplo celda classes: {cell_classes}")
    cell_html = str(cells[0])[:200]
    print(f"HTML celda: {cell_html}")