"""Analizar estructura de cargos y servicios en guestfolio con datos."""
import re
from bs4 import BeautifulSoup

with open("guestfolio_23419.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")
tables = soup.find_all("table")

print(f"=== TABLA 2 (CARGOS/ESTANCIAS) ===")
headers = [th.get_text(strip=True) for th in tables[1].find_all("th")]
print(f"Headers: {headers}")

rows = tables[1].find_all("tr")[1:]  # skip header
for row in rows:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    if any(values):  # Skip empty
        print(f"  Row: {values}")

print(f"\n=== TABLA 3 (SERVICIOS) ===")
headers = [th.get_text(strip=True) for th in tables[2].find_all("th")]
print(f"Headers: {headers}")

rows = tables[2].find_all("tr")[1:]
for row in rows:
    cells = row.find_all(["td", "th"])
    values = [c.get_text(strip=True) for c in cells]
    if any(values):
        print(f"  Row: {values}")

# Extraer totales
# Buscar texto "Total"
for match in soup.find_all(string=re.compile(r"Total", re.I)):
    print(f"  Texto: {match}")