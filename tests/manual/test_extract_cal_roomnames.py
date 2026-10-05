"""Extraer room names + numbers (capacidad implícita) del calendar sidebar."""
import re
import json
from pathlib import Path

from bs4 import BeautifulSoup

html = Path(__file__).parent.joinpath("calendar_rendered.html").read_text(
    encoding="utf-8", errors="replace"
)

soup = BeautifulSoup(html, "html.parser")

# Extract from calendar_rooms_dott
room_divs = soup.find_all(attrs={"class": "calendar_rooms_dott"})
print(f"Room div elements: {len(room_divs)}")

rooms = []
for div in room_divs:
    text = div.get_text(separator=" ", strip=True)
    match = re.match(r'^(.+?)(\d+)$', text.strip())
    if match:
        rooms.append({"name": match.group(1).strip(), "number": match.group(2).strip()})
    else:
        nums = re.findall(r'\d+', text)
        rooms.append({"name": re.sub(r'\d+', '', text).strip(), "number": nums[0] if nums else ""})

# Map capacity
capacity_map = {"Matrimonial": 2, "Doble Individual": 2, "Triple": 3, "Quadruple": 4,
    "Quintuple": 5, "king": 2, "Suite": 2, "Dobl": 2}
for r in rooms:
    r["capacity"] = capacity_map.get(r["name"], 1)

unique_rooms = []
seen = set()
for r in rooms:
    key = (r["name"], r["number"])
    if key not in seen:
        seen.add(key)
        unique_rooms.append(r)

print(f"\n🏨 Rooms ({len(unique_rooms)}):")
for r in unique_rooms:
    print(f"  {r['name']} (#{r['number']}): cap={r['capacity']}")

# Save
summary = {"total_rooms": len(unique_rooms), "rooms": unique_rooms}
Path(__file__).parent.joinpath("calendar_rooms_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"\n✅ Saved: {json.dumps(summary, indent=2, ensure_ascii=False)}")