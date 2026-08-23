"""Debug: todas las tablas del folio con sus datos reales."""
from bs4 import BeautifulSoup

with open("guestfolio_23419.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")
tables = soup.find_all("table")

for i, table in enumerate(tables):
    rows = table.find_all("tr")
    if len(rows) <= 1:
        continue  # Skip empty tables
    print(f"\n=== TABLA {i+1} ({len(rows)} rows) ===")
    for j, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        values = [c.get_text(strip=True) for c in cells]
        non_empty = [v for v in values if v]
        if len(non_empty) > 1:  # Skip rows with only 1 value
            print(f"  Fila {j}: {values[:12]}")