"""Analizar calendar HTML renderizado: botones, room rows, drag-drop."""
import re
from pathlib import Path

from bs4 import BeautifulSoup

with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Find all buttons
buttons = soup.find_all("button")
print(f"Total buttons: {len(buttons)}")
interesting_btns = [b for b in buttons if any(kw in b.get_text().lower() for kw in ["close", "open", "block", "room", "estado", "disp", "status", "ocup", "bloqu"])]
print(f"Interesting buttons ({len(interesting_btns)}):")
for btn in interesting_btns[:10]:
    onclick = btn.get("onclick", "")
    print(f"  '{btn.get_text(strip=True)}' onclick={onclick[:80]}")

# Find reservation items with resid
res_items = soup.find_all(attrs={"resid": True})
print(f"\nReservation items: {len(res_items)}")
if res_items:
    first = res_items[0]
    print(f"  Classes: {first.get('class', [])}")
    parent = first.parent
    print(f"  Parent class: {parent.get('class', [])}")

# Onclick handlers
onclick_elems = soup.find_all(attrs={"onclick": True})
print(f"\nElements with onclick: {len(onclick_elems)}")
action_types = {}
for el in onclick_elems:
    onclick = el.get("onclick", "")
    for kw in ["block", "close", "open", "status", "availability", "room", "date", "reserve"]:
        if kw in onclick.lower():
            action_types[kw] = action_types.get(kw, 0) + 1
print(f"Action keywords: {action_types}")

for el in onclick_elems[:5]:
    onclick = el.get("onclick", "")
    if len(onclick) > 10:
        print(f"  {onclick[:150]}")

# Tables
tables = soup.find_all("table")
print(f"\nTables: {len(tables)}")
for i, t in enumerate(tables[:5]):
    headers = [th.get_text(strip=True) for th in t.find_all("th")]
    if headers:
        print(f"  Tabla {i+1}: {headers[:6]}")

# Close/open elements
close_open = soup.find_all(attrs={"class": re.compile(r"close|open|block|avail", re.I)})
print(f"\nClose/open/block elements: {len(close_open)}")

# Room patterns
room_cells = re.findall(r'room[\w_-]{0,20}', html, re.I)
room_unique = sorted(set(room_cells))[:10]
print(f"\nRoom patterns: {room_unique}")

# Save summary
Path(__file__).parent.joinpath("calendar_analysis.txt").write_text(
    f"Buttons: {len(buttons)}\n"
    f"Res items: {len(res_items)}\n"
    f"Tables: {len(tables)}\n"
    f"Onclick elems: {len(onclick_elems)}\n"
    f"Action keywords: {action_types}\n"
    f"Interesting buttons: {len(interesting_btns)}\n"
)
print(f"\nSaved analysis")