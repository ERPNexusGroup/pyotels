"""Consultar reservas del día: ingresos, estancias y salidas por status."""
import re
import json
from datetime import datetime
from sqlalchemy import create_engine, select, func, cast, Numeric
from sqlalchemy.orm import Session
from otelms.config.settings import get_settings
from otelms.domain.entities import Reservation, Guest, Room, Service, Payment

settings = get_settings()
engine = create_engine(settings.get_database_url_sync())

today = datetime.now().date()
print(f"=== Reservas del dia: {today} ===\n")

with Session(engine) as session:
    status_map = {1: "Reservacion", 2: "Check-in", 3: "Check-out", 4: "Cancelada", 5: "No-show"}

    # INGRESOS (check_in = hoy)
    ingresos = session.execute(select(Reservation).where(func.date(Reservation.check_in) == today)).scalars().all()
    print(f"[INGRESOS] (check-in hoy): {len(ingresos)}")
    for r in ingresos:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Total: ${r.total_price} | Status: {status_map.get(r.status, r.status)}")

    # SALIDAS (check_out = hoy)
    salidas = session.execute(select(Reservation).where(func.date(Reservation.check_out) == today)).scalars().all()
    print(f"\n[SALIDAS] (check-out hoy): {len(salidas)}")
    for r in salidas:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Total: ${r.total_price} | Status: {status_map.get(r.status, r.status)}")

    # ESTANCIAS (check_in <= hoy <= check_out)
    estancias = session.execute(select(Reservation).where(Reservation.check_in <= today, Reservation.check_out >= today)).scalars().all()
    print(f"\n[ESTANCIAS] (activas hoy): {len(estancias)}")
    for r in estancias:
        g = session.get(Guest, r.guest_id) if r.guest_id else None
        print(f"  #{r.id}: {g.full_name if g else 'N/A'} | Status: {status_map.get(r.status, r.status)}")

    # Status counts
    all_res = session.execute(select(Reservation)).scalars().all()
    status_counts = {}
    for r in all_res:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    print(f"\n[TOTAL BD]: {len(all_res)}")
    for s, count in sorted(status_counts.items()):
        print(f"  Status {s} ({status_map.get(s, '?')}): {count}")