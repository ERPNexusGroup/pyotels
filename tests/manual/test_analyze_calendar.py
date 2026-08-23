"""Analizar estructura HTML del calendar para extraer reservas."""
import re
import html
from bs4 import BeautifulSoup

with open("calendario_debug.html", "r", encoding="utf-8") as f:
    content = f.read()

soup = BeautifulSoup(content, "html.parser")

# Todos los items con resid
res_items = soup.find_all(attrs={"resid": True})
print(f"Items con resid: {len(res_items)}")

if res_items:
    first = res_items[0]
    print(f"\nPrimer item:")
    print(f"resid: {first.get('resid')}")
    print(f"status: {first.get('status')}")
    print(f"classes: {first.get('class')}")

    # Extraer texto
    text = first.get_text(strip=True)
    print(f"Texto: {text[:200]}")

    # Extraer datos
    booking_name = first.find(class_=re.compile(r"booking_nam", re.I))
    if booking_name:
        print(f"Booking name: {booking_name.get_text(strip=True)[:100]}")

    room = first.find(class_=re.compile(r"room", re.I))
    if room:
        print(f"Room: {room.get_text(strip=True)[:50]}")

    # Links
    links = first.find_all("a")
    for link in links[:3]:
        href = link.get("href", "")
        if "folio" in href or "guestfolio" in href:
            print(f"Link: {href}")

# Analizar todos los tipos de datos
all_booking_names = soup.find_all(class_=re.compile(r"booking_nam", re.I))
print(f"\nBooking names: {len(all_booking_names)}")
if all_booking_names:
    print(f"Sample: {all_booking_names[0].get_text(strip=True)[:50]}")

# IDs de reserva
res_ids = [item.get("resid") for item in res_items]
print(f"\nRes IDs: {sorted(set(res_ids))[:10]}")
print(f"Total únicos: {len(set(res_ids))}")

# Status
statuses = [item.get("status") for item in res_items]
status_counts = {}
for s in statuses:
    status_counts[s] = status_counts.get(s, 0) + 1
print(f"Status counts: {status_counts}")