"""Consultar habitaciones 201, 103, 209 desde BD y calendar HTML."""
import re
import json
from html import unescape
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from otelms.config.settings import get_settings
from otelms.domain.entities import Reservation, Guest, Room, Service, Payment

settings = get_settings()
engine = create_engine(settings.get_database_url_sync())

print("=== Habitaciones en BD ===")
with Session(engine) as session:
    for num in ["201", "103", "209"]:
        r = session.execute(select(Room).where(Room.name == num)).scalar_one_or_none()
        if r:
            cat = r.category.name if r.category else "N/A"
            print(f"  Hab. {num}: {cat}, active={r.is_active}")
        else:
            print(f"  Hab. {num}: NO EN BD")

# Calendar HTML
with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

calendar_items = re.findall(r'data-title="([^"]*)"', html)
print(f"\n=== Calendar HTML: {len(calendar_items)} tooltips ===")

for room_num in ["201", "103", "209"]:
    matches = [t for t in calendar_items if room_num in t]
    print(f"\nRoom {room_num}: {len(matches)} reservas en tooltips")
    for m in matches[:2]:
        decoded = unescape(m)
        print(f"  {decoded[:120]}")

# All room refs in calendar
room_refs = set()
for t in calendar_items:
    decoded = unescape(t)
    room_match = re.search(r'(Habitaci[oó]n|Room|hab)[^,]*?(\d+)', decoded)
    if room_match:
        room_refs.add(room_match.group(2))
print(f"\n📺 Todas las room refs en calendar: {sorted(room_refs)}")