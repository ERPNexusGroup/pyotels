"""Parsea tablas del guestfolio debug HTML para identificar estructura de datos."""
import re
from bs4 import BeautifulSoup

with open("guestfolio_debug.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")
tables = soup.find_all("table")

print(f"Tablas encontradas: {len(tables)}")

for i, table in enumerate(tables):
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = table.find_all("tr")
    print(f"\n📋 Tabla {i+1}: {len(rows)} filas")
    print(f"  Headers: {headers}")

    for row in rows[1:3]:  # Máximo 2 rows por tabla
        cells = row.find_all(["td", "th"])
        values = [cell.get_text(strip=True) for cell in cells]
        print(f"  Row: {values}")

# Extraer reserva info específica
# Buscar elementos con resid, reservation info, guest info
res_info = re.search(r"reservación.{0,5}(?:\s*\n?.*?){0,200}", content[:2000])
if res_info:
    print(f"\nRes info: {res_info.group()[:200]}")

# Buscar información de habitación
room_info = re.search(r"Habitaci[oó]n.{0,2}(\d+[^\n<]*)", content)
if room_info:
    print(f"\nRoom: {room_info.group()[:100]}")
# Guest name
guest_name = re.search(r"hu([ée]sped|ésped).{0,2}([\w\s]+)", content, re.I)
if guest_name:
    print(f"\nGuest: {guest_name.group()[:100]}")

# AJAX endpoints
ajax_links = re.findall(r'ajaxlink\s*=\s*"([^"]+)"', content)
print(f"\n🔌 AJAX endpoints: {ajax_links[:10]}")