"""Extraer room_number + room_type desde calendar_rendered.html (Playwright)."""
import re
import json
from html import unescape
from collections import Counter

with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# Extract room names from calendar_rooms_dott sidebar
room_divs = re.findall(r'<div class="calendar_rooms_dott">\s*([^<]+?)\s*</div>', html)
print(f"📺 Sidebar rooms ({len(room_divs)}):")
for name in room_divs:
    print(f"  {name}")

# Extract room numbers + types from calendar_item tooltips
tooltips = re.findall(r'data-title="([^"]{0,500})"', html)
print(f"\n📅 Calendar tooltips: {len(tooltips)}")

room_info = []
for t in tooltips[:5]:
    decoded = unescape(t)
    match = re.search(r'(?:Habitaci[oó]n|Room)[:\s]*(\d+)\s+(\w+)', decoded)
    if match:
        room_info.append({"room_number": match.group(1), "room_type": match.group(2)})
        print(f"  Room {match.group(1)}: {match.group(2)}")
    else:
        print(f"  Tooltip: {decoded[:80]}")

# Check for rooms 201, 103, 209
for rn in ["201", "103", "209"]:
    count = html.count(rn)
    print(f"\n  Room {rn}: {count} refs in HTML")

# Booking room allocations
booking_rooms = re.findall(r'(Habitaci[oó]n|Room)\s*[:\s]*(\d+)', html)
print(f"\n📋 Booking room allocations ({len(booking_rooms)}): {booking_rooms[:10]}")