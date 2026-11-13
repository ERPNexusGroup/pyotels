"""Extraer room names + status + capacidad del calendar_items."""
import re
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

html = Path(__file__).parent.joinpath("calendar_rendered.html").read_text(
    encoding="utf-8", errors="replace"
)

soup = BeautifulSoup(html, "html.parser")

# Extract data-title from calendar_items (resid elements)
res_items = soup.find_all(attrs={"resid": True})
print(f"Calendar items: {len(res_items)}")

room_data = defaultdict(list)

for item in res_items:
    resid = item.get("resid", "")
    status = item.get("status", "0")
    data_title = item.get("data-title", "")

    if not data_title:
        continue

    import html as html_module
    decoded = html_module.unescape(data_title)

    # Extract room name from tooltip
    room_match = re.search(r'Habitaci[oó]n[:.\s]*\d+\s+(\w+)', decoded)
    if not room_match:
        room_match = re.search(r'(Matrimonial|Dobl|Simple|Suite|King|Queen|BODEGA|RECEPCION)', decoded, re.I)

    room_name = room_match.group(1) if room_match else "Unknown"

    # Extract date range
    date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', decoded)
    dates = f"{date_match.group(1)}-{date_match.group(2)}" if date_match else ""

    room_data[room_name].append({
        "resid": resid,
        "dates": dates,
        "status": status,
    })

print(f"\n🏨 Rooms with bookings:")
for room_name, bookings in room_data.items():
    print(f"  {room_name}: {len(bookings)} bookings")
    for b in bookings[:2]:
        print(f"    {b['resid']}: {b['dates']} status={b['status']}")

# Sidebar room names
room_divs = soup.find_all(attrs={"class": "calendar_rooms_dott"})
room_names = set()
for div in room_divs:
    text = div.get_text(strip=True)
    room_matches = re.findall(r'(Matrimonial|Dobl|Simple|Suite|King|Queen|BODEGA|RECEPCION)', div.prettify(), re.I)
    room_names.update(room_matches)
print(f"\n📋 Sidebar room names: {room_names}")

# Status classes
status_counts = dict(Counter(re.findall(r'(bg_\w+)', html)))
print(f"\n📊 Status classes: {status_counts}")

# Save
import json
summary = {
    "total_bookings": len(res_items),
    "rooms": {k: len(v) for k, v in room_data.items()},
    "sidebar_rooms": list(room_names),
    "statuses": status_counts,
}
Path(__file__).parent.joinpath("calendar_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False)
)
print(f"\n✅ Summary: {json.dumps(summary, indent=2, ensure_ascii=False)}")