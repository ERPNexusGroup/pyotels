"""Explorar UI de calendar: cómo cerrar/abrir fechas vía drag-drop."""
import re
import json
from collections import Counter
from bs4 import BeautifulSoup

with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Reservation items
items = soup.find_all(attrs={"resid": True})
print(f"Total reservation items: {len(items)}")

statuses = set()
for item in items:
    statuses.add(item.get("status", ""))
print(f"Status values: {statuses}")

bg_classes = re.findall(r'bg_(\w+)', html)
print(f"BG classes: {Counter(bg_classes)}")

for item in items[:3]:
    resid = item.get("resid", "")
    status = item.get("status", "")
    data_title = item.get("data-title", "")
    import html as html_lib
    decoded = html_lib.unescape(data_title)
    date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', decoded)
    dates = f"{date_match.group(1)} - {date_match.group(2)}" if date_match else "N/A"
    room_match = re.search(r'Habitaci[oó]n:\s*\d+\s+(.+?)(?:\r|$)', decoded)
    room = room_match.group(1) if room_match else "N/A"
    print(f"  Res #{resid}: room={room}, dates={dates}, status={status}")

# JS functions
js_functions = re.findall(r'function\s+(\w+)\s*\([^)]*\)\s*\{', html)
print(f"\n📜 JS functions: {js_functions[:15]}")

# Availability/blocking functions
avail_funcs = re.findall(r'function\s+\w*[Bb]lock\w*\s*\([^)]*\)', html)
print(f"Block functions: {avail_funcs}")

# Toolbar buttons
toolbar_btns = soup.find_all(attrs={"class": re.compile(r"toolbar|tool-btn|btn", re.I)})
print(f"\nToolbar buttons: {len(toolbar_btns)}")
for btn in toolbar_btns[:5]:
    print(f"  '{btn.get_text(strip=True)}' onclick={btn.get('onclick', '')[:60]}")

# Modals
modals = soup.find_all(attrs={"class": re.compile(r"modal|popup|dialog", re.I)})
print(f"\nModals: {len(modals)}")

# Look for room status modal (estado de habitación)
estado_btns = soup.find_all(attrs={"onclick": True})
print(f"\n🔍 Click handlers: {len(estado_btns)}")
for eb in estado_btns:
    onclick = eb.get("onclick", "")
    if len(onclick) > 5:
        print(f"  {onclick[:120]}")

# Find setmonth and other calendar functions
calendar_funcs = re.findall(r'(setmonth|navigate|change_room|room_status|set_room_status|block_room|availability)[^;]{0,100}', html)
print(f"\nCalendar functions: {calendar_funcs[:10]}")

# Look for room status modal
room_status_html = re.findall(r'(room_status|estado_habitacion|room.status|habitacion.status)[^<]{0,100}', html, re.I)
print(f"\nRoom status refs: {room_status_html[:5]}")