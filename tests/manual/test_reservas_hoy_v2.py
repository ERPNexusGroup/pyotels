"""Consultar reservas de hoy: ingresos, estancias, salidas + rooms 201/103/209."""
import re
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from otelms.config.settings import get_settings
from otelms.domain.entities import Reservation, Guest, Room, Service, Payment

settings = get_settings()
engine = create_engine(settings.get_database_url_sync())
today = date(2026, 8, 23)

print(f"=== RESERVAS DE HOY: {today} ===\n")

with Session(engine) as session:
    # Get all reservations
    all_res = session.execute(select(Reservation)).scalars().all()
    all_res.sort(key=lambda r: r.check_in)

    # Classify
    ingresos = [r for r in all_res if r.check_in.date() == today]
    salidas = [r for r in all_res if r.check_out.date() == today]
    estancias = [r for r in all_res if r.check_in.date() <= today <= r.check_out.date()]

    # Status names
    status_map = {1: "Reservación", 2: "Check-in", 3: "Check-out", 4: "Cancelada", 5: "No-show"}

    print(f"[INGRESOS] (check-in hoy): {len(ingresos)}")
    for r in ingresos:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        room = session.get(Room, r.room_id) if r.room_id else None
        room_name = room.name if room else "N/A"
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Hab: {room_name} | Adults: {r.adults} | ${r.total_price} | Status: {status_map.get(r.status, r.status)}")

    print(f"\n[SALIDAS] (check-out hoy): {len(salidas)}")
    for r in salidas:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        room = session.get(Room, r.room_id) if r.room_id else None
        room_name = room.name if room else "N/A"
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Hab: {room_name} | Adults: {r.adults}")

    print(f"\n[ESTANCIAS] (activas hoy): {len(estancias)}")
    for r in estancias:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        room = session.get(Room, r.room_id) if r.room_id else None
        room_name = room.name if room else "N/A"
        ci = r.check_in.date()
        co = r.check_out.date()
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Hab: {room_name} | {ci}→{co} | Status: {status_map.get(r.status, r.status)} | ${r.total_price}")

    # Rooms in BD
    rooms = session.execute(select(Room)).scalars().all()
    print(f"\n[HABITACIONES EN BD]: {len(rooms)}")
    for r in rooms:
        print(f"  #{r.name}: {r.category.name if r.category else 'N/A'} (cap: {r.max_occupancy})")

    # Check rooms 201, 103, 209
    print(f"\n=== Rooms 201, 103, 209 ===")
    for room_num in ["201", "103", "209"]:
        room = session.execute(select(Room).where(Room.name == room_num)).scalar_one_or_none()
        if room:
            cat = room.category.name if room.category else "N/A"
            print(f"  Hab {room_num}: {cat}, cap={room.max_occupancy}")
        else:
            print(f"  Hab {room_num}: NO EN BD")

    # Status distribution
    status_counts = {}
    for r in all_res:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    print(f"\n[STATUS DISTRIBUTION]:")
    for s, c in sorted(status_counts.items()):
        print(f"  {status_map.get(s, s)}: {c}")

    # Payments summary
    payments = session.execute(select(Payment)).scalars().all()
    print(f"\n[PAYMENTS]: {len(payments)}")
    pay_methods = {}
    for p in payments:
        method = p.payment_method
        pay_methods[method] = pay_methods.get(method, 0) + 1
    print(f"  Methods: {pay_methods}")