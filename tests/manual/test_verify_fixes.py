"""Verificar BD después de fixes: rooms, guests, reservations."""
import re
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from otelms.config.settings import get_settings
from otelms.domain.entities import Reservation, Guest, Room

settings = get_settings()
engine = create_engine(settings.get_database_url_sync())

today = __import__("datetime").date(2026, 8, 23)

with Session(engine) as session:
    # Rooms
    rooms = session.execute(select(Room)).scalars().all()
    print(f"🏨 HABITACIONES ({len(rooms)}):")
    for r in rooms[:15]:
        cat = r.category.name if r.category else "N/A"
        print(f"  #{r.name}: {cat} (cap={r.max_occupancy})")

    # Check 201, 103, 209
    print(f"\n=== Rooms 201, 103, 209 ===")
    for rn in ["201", "103", "209"]:
        room = session.execute(select(Room).where(Room.name == rn)).scalar_one_or_none()
        if room:
            cat = room.category.name if room.category else "N/A"
            print(f"  Hab {rn}: ✅ en BD ({cat})")
        else:
            print(f"  Hab {rn}: ❌ no en BD")

    # Guests
    guests = session.execute(select(Guest)).scalars().all()
    print(f"\n👥 GUESTs ({len(guests)}):")
    for g in guests[:5]:
        print(f"  {g.first_name} {g.last_name} | doc={g.document_type} {g.doc_number} | email={g.email or 'N/A'}")

    # Reservation statuses
    status_map = {1: "Reservación", 2: "Check-in", 3: "Check-out", 4: "Cancelada", 5: "No-show"}
    
    # INGRESOS
    all_res = session.execute(select(Reservation)).scalars().all()
    ingresos = [r for r in all_res if r.check_in.date() == today]
    salidas = [r for r in all_res if r.check_out.date() == today]
    estancias = [r for r in all_res if r.check_in.date() <= today <= r.check_out.date()]

    print(f"\n📅 RESERVAS DE HOY ({today}):")
    print(f"  [INGRESOS]: {len(ingresos)} reservas")
    for r in ingresos:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        room = session.get(Room, r.room_id) if r.room_id else None
        print(f"    #{r.id}: {g.full_name if g else 'N/A'} | Hab: {room.name if room else 'N/A'}")

    print(f"\n  [SALIDAS]: {len(salidas)} reservas")
    for r in salidas:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        print(f"    #{r.id}: {g.full_name if g else 'N/A'} | {r.check_out.date()}")

    print(f"\n  [ESTANCIAS]: {len(estancias)} reservas")
    for r in estancias[:5]:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        s = status_map.get(r.status, str(r.status))
        print(f"    #{r.id}: {g.full_name if g else 'N/A'} | Status: {s}")

    # Status distribution
    status_counts = {}
    for r in all_res:
        status_counts[status_map.get(r.status, str(r.status))] = status_counts.get(status_map.get(r.status, str(r.status)), 0) + 1
    print(f"\n📊 STATUS DISTRIBUTION:")
    for s, c in sorted(status_counts.items()):
        print(f"  {s}: {c}")