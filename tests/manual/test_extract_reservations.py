"""Extraer datos completos de todas las reservas del calendar."""
import re
import json
from bs4 import BeautifulSoup

with open("calendario_debug.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")
res_items = soup.find_all(attrs={"resid": True})

reservations = []

for item in res_items:
    resid = item.get("resid")
    status = item.get("status")
    text = item.get_text(strip=True)
    booking_name_elem = item.find(class_=re.compile(r"booking_nam", re.I))
    booking_name = booking_name_elem.get_text(strip=True) if booking_name_elem else ""

    # Parsear booking_name: "R:23229,  BODEGA, Venta directa, 0"
    parts = [p.strip() for p in booking_name.split(",")]
    reservation_id = parts[0].replace("R:", "") if parts else ""
    room_type = parts[1] if len(parts) > 1 else ""
    channel = parts[2] if len(parts) > 2 else ""
    room_count = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    # Extraer links
    folio_link = ""
    edit_link = ""
    guest_link = ""
    for link in item.find_all("a"):
        href = link.get("href", "")
        if "folio" in href:
            folio_link = href
        elif "edit" in href:
            edit_link = href
        elif "guestfolio" in href:
            guest_link = href

    reservations.append({
        "resid": resid,
        "status": status,
        "reservation_id": reservation_id,
        "room_type": room_type,
        "channel": channel,
        "room_count": room_count,
        "folio_url": folio_link,
        "edit_url": edit_link,
        "guest_url": guest_link,
    })

print(f"Total reservas: {len(reservations)}")
print(json.dumps(reservations[:2], indent=2, ensure_ascii=False))

# Guardar
with open("reservations_extracted.json", "w") as f:
    json.dump(reservations, f, indent=2, ensure_ascii=False)
print(f"\nSaved to reservations_extracted.json")