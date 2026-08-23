"""Test E2E: sync completo con BD sync SQLite."""
import hashlib
import json
from datetime import datetime

import requests
import urllib3
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from otelms.config.settings import get_settings
from otelms.config.constants import OtelMSUrls
from otelms.domain.entities import Base, Reservation, Service
from otelms.scraping.folio_extract import parse_folio, extract_reservations_from_calendar
from otelms.utils.logging import get_logger

urllib3.disable_warnings()
logger = get_logger(__name__)


def login_session(hotel_id: str) -> requests.Session:
    """Login HTTP sync, retorna session con cookies válidas."""
    settings = get_settings()
    session = requests.Session()
    session.headers.update({
        "User-Agent": settings.browser_user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    session.verify = False

    session.get(f"https://desktop.otelms.com/login_c2/single_login?hmsid={hotel_id}", timeout=15)
    r = session.post(
        "https://desktop.otelms.com/login_c2/do_single_login",
        data={"hotel": hotel_id, "login": settings.otelms_default_username,
              "password": settings.otelms_default_password, "action": "login"},
        headers={"Referer": f"https://desktop.otelms.com/login_c2/single_login?hmsid={hotel_id}"},
        timeout=15,
    )

    if "reservation_c2/calendar" not in r.text:
        raise RuntimeError("Login fallido")
    logger.info("Login exitoso")
    return session


def sync_to_db(session: requests.Session, db, hotel_id: str) -> dict:
    """Sync completo: calendar → folios → BD."""
    # 1. Calendar
    cal_resp = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
    reservations = extract_reservations_from_calendar(cal_resp.text)
    logger.info(f"Extracted {len(reservations)} reservations")

    created = updated = svc_created = errors = 0

    for res in reservations:
        try:
            # Upsert reservation
            sync_hash = hashlib.sha256(
                json.dumps(res, sort_keys=True, default=str).encode()
            ).hexdigest()[:64]

            existing = db.get(Reservation, str(res["resid"]))
            if existing:
                if existing.sync_hash != sync_hash:
                    existing.check_in = res.get("check_in")
                    existing.check_out = res.get("check_out")
                    existing.status = res.get("status", 1)
                    existing.notes = res.get("comments", "")
                    existing.sync_hash = sync_hash
                    db.merge(existing)
                updated += 1
            else:
                db.add(Reservation(
                    id=str(res["resid"]),
                    hotel_id=hotel_id,
                    room_id="room_default",
                    check_in=res.get("check_in"),
                    check_out=res.get("check_out"),
                    status=res.get("status", 1),
                    adults=res.get("guest_count") or 1,
                    source=res.get("channel", ""),
                    notes=res.get("comments", ""),
                    sync_hash=sync_hash,
                ))
                created += 1

            # 2. Folio → servicios/charges
            fol_resp = session.get(
                f"https://desktop.otelms.com/reservation_c2/folio/{res['resid']}",
                timeout=20,
            )
            if fol_resp.status_code == 200:
                folio = parse_folio(fol_resp.text, str(res["resid"]))

                for svc in folio["services"]:
                    svc_id = f"svc_{res['resid']}_{svc.get('id', '')}"
                    svc_obj = Service(
                        id=svc_id,
                        reservation_id=str(res["resid"]),
                        date=datetime.utcnow(),
                        title=svc.get("name", ""),
                        description=svc.get("legal_entity", ""),
                        quantity=float(svc.get("quantity") or 1) or 1,
                        price=float(svc.get("price") or 0),
                        total=float(svc.get("amount") or 0),
                    )
                    db.merge(svc_obj)
                    svc_created += 1

                for charge in folio["room_charges"]:
                    charge_id = f"rc_{res['resid']}_{charge.get('date', '')}"
                    svc_obj = Service(
                        id=charge_id,
                        reservation_id=str(res["resid"]),
                        date=datetime.fromisoformat(charge.get("date", "2000-01-01")),
                        title=charge.get("description", ""),
                        quantity=1.0,
                        price=0.0,
                        total=float(charge.get("amount") or 0),
                    )
                    db.merge(svc_obj)
                    svc_created += 1

        except Exception as e:
            errors += 1
            logger.error(f"Error res {res.get('resid')}: {e}")

    db.commit()

    return {
        "reservations": len(reservations),
        "created": created,
        "updated": updated,
        "services_created": svc_created,
        "errors": errors,
    }


def test_e2e():
    settings = get_settings()
    db_url = settings.get_database_url_sync()

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # Login + sync
    session = login_session("18330")
    result = sync_to_db(session, db, "18330")
    print(json.dumps(result, indent=2, default=str))

    # Verify
    total_res = db.query(Reservation).filter(Reservation.hotel_id == "18330").count()
    total_svc = db.query(Service).count()
    print(f"\n📊 BD: {total_res} reservations, {total_svc} services")

    # Sample
    sample = db.query(Reservation).first()
    if sample:
        print(f"Sample: id={sample.id} status={sample.status} notes={sample.notes[:30]}")

    db.close()
    engine.dispose()


if __name__ == "__main__":
    test_e2e()