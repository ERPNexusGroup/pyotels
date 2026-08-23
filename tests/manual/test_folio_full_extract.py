"""Extrae datos completos de servicios y pagos del folio."""
import requests
import urllib3
import re
from bs4 import BeautifulSoup
from decimal import Decimal
from otelms.config.settings import get_settings

urllib3.disable_warnings()
s = get_settings()

session = requests.Session()
session.headers.update({"User-Agent": s.browser_user_agent, "Content-Type": "application/x-www-form-urlencoded"})
session.verify = False
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
session.post("https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel":"18330","login":s.otelms_default_username,"password":s.otelms_default_password,"action":"login"},
    headers={"Referer":"https://desktop.otelms.com/login_c2/single_login?hmsid=18330"}, timeout=15)

res_id = 23229
fol = session.get(f"https://desktop.otelms.com/reservation_c2/folio/{res_id}", timeout=30)
print(f"Folio {res_id}: {fol.status_code}, {len(fol.text)} bytes")

soup = BeautifulSoup(fol.text, "html.parser")
tables = soup.find_all("table")

print(f"\nTotal tablas: {len(tables)}")

# Todas las tablas con datos
for i, table in enumerate(tables):
    rows = table.find_all("tr")
    if len(rows) <= 1:
        continue
    print(f"\n=== TABLA {i+1} ({len(rows)} rows) ===")
    for j, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        values = [c.get_text(strip=True) for c in cells]
        non_empty = [v for v in values if v.strip()]
        if non_empty:
            print(f"  Fila {j}: {non_empty[:15]}")