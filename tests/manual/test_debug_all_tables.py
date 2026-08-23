"""Debug: tablas 4-11 del folio con datos reales."""
from bs4 import BeautifulSoup

with open("guestfolio_23419.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")
tables = soup.find_all("table")

for i, table in enumerate(tables[3:], start=4):  # Tabla 4
    rows = table.find_all("tr")
    print(f"\n=== TABLA {i} ({len(rows)} rows) ===")
    for j, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        values = [c.get_text(strip=True) for c in cells]
        non_empty = [v for v in values if v.strip()]
        if len(non_empty) > 1:
            print(f"  Fila {j}: {non_empty[:15]}")