"""Verificar extract_room_type y extraer room_number del folio."""
import re
import json
from html import unescape
from otelms.scraping.room_extract import extract_room_type

with open("folio_23419_full.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

room_type = extract_room_type(html)
print(f"folio_23419 room_type: {room_type}")

# Look for room number pattern in the folio HTML
match = re.search(r'(?:Habitaci[oó]n|Room)[:\s]*(\d+)\s+(\w+)', html)
if match:
    print(f"  room_number: {match.group(1)}, room_type: {match.group(2)}")

# Check data-title attribute for room info
items = re.findall(r'data-title="([^"]*)"', html)
print(f"\nCalendar tooltips: {len(items)}")
for item in items[:2]:
    decoded = unescape(item)
    rm = re.search(r'(?:Habitaci[oó]n|Room)[:\s]*(\d+)\s+(\w+)', decoded)
    if rm:
        print(f"  room_number: {rm.group(1)}, room_type: {rm.group(2)}")
    else:
        print(f"  {decoded[:80]}")