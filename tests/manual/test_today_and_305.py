"""Consultar reservas del día de hoy desde BD + explorar room 305 calendar."""
import re
import json
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from otelms.config.settings import get_settings
from otelms.domain.entities import Reservation, Guest, Room, Service, Payment

settings = get_settings()
engine = create_engine(settings.get_database_url_sync())

with Session(engine) as session:
    today = datetime.now().date()

    # Reservas activas hoy
    stmt = select(Reservation).where(
        Reservation.check_in <= today,
        Reservation.check_out >= today
    )
    today_res = session.execute(stmt).scalars().all()

    print(f"📅 RESERVAS ACTIVAS HOY ({today}):")
    print(f"Total: {len(today_res)}")
    for r in today_res:
        print(f"  #{r.id}: {r.guest.full_name if r.guest else 'N/A'}")
        print(f"    Check-in: {r.check_in}, Check-out: {r.check_out}")
        print(f"    Adults: {r.adults}, Status: {r.status}")
        print(f"    Source: {r.source}")

    # Habitación 305 en BD
    room_305 = session.execute(select(Room).where(Room.name == "305")).scalar_one_or_none()
    print(f"\n🏨 Habitación 305 en BD:")
    if room_305:
        cat = room_305.category.name if room_305.category else "N/A"
        print(f"  Room #{room_305.room_number}: {cat} ({room_305.status})")
    else:
        print("  No encontrada en BD")
    
    # Todas las hab. en BD
    rooms = session.execute(select(Room)).scalars().all()
    print(f"\n📋 Hab. en BD ({len(rooms)}):")
    for r in rooms:
        print(f"  #{r.name}: {r.category.name if r.category else 'N/A'}")

# Check calendar HTML para room 305
with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# All room names in sidebar
room_names_html = re.findall(r'calendar_rooms_dott">\s*([^<]+?)\s*</div>', html)
print(f"\n📺 Rooms en calendar HTML:")
for name in room_names_html:
    print(f"  {name.strip()}")

r305 = html.count("305")
print(f"\n🔍 Referencias a 305 en HTML: {r305}")