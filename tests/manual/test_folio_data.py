"""Extraer datos completos de servicios y pagos del folio."""
import re
from bs4 import BeautifulSoup
from decimal import Decimal

import requests, urllib3
urllib3.disable_warnings()
from otelms.config.settings import get_settings
s = get_settings()

session = requests.Session()
session.headers.update({"User-Agent": s.browser_user_agent, "Content-Type": "application/x-www-form-urlencoded"})
session.verify = False
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
session.post("https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel":"18330","login":s.otelms_default_username,"password":s.otelms_default_password,"action":"login"},
    headers={"Referer":"https://desktop.otelms.com/login_c2/single_login?hmsid=18330"}, timeout=15)

fol = session.get("https://desktop.otelms.com/reservation_c2/folio/23229", timeout=30)
soup = BeautifulSoup(fol.text, "html.parser")
tables = soup.find_all("table")

# TABLA 2 (índice 1): Servicios
print("=== SERVICIOS ===")
rows = tables[1].find_all("tr")[1:]  # skip header
for row in rows:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    non_empty = [v for v in values if v.strip()]
    if len(non_empty) > 1 and "Total:" not in values:
        print(f"  {non_empty}")

# TABLA 3 (índice 2): Pagos
print("\n=== PAGOS ===")
rows = tables[2].find_all("tr")[1:]
for row in rows:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    non_empty = [v for v in values if v.strip()]
    if len(non_empty) > 1 and "Total:" not in values:
        print(f"  {non_empty}")

# TABLA 8 (índice 7): Room charges
print("\n=== ROOM CHARGES ===")
rows = tables[7].find_all("tr")[1:]
for row in rows[:3]:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    non_empty = [v for v in values if v.strip()]
    if non_empty:
        print(f"  {non_empty}")

# TABLA 11 (índice 10): Services (ruso)
print("\n=== SERVICES (ruso) ===")
rows = tables[10].find_all("tr")[1:]
for row in rows:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    if values:
        print(f"  {values}")