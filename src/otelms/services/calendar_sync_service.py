"""Servicio completo de sync: calendar → folios → BD (reservas, guests, services, payments)."""
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import cast

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from otelms.config.settings import Settings, get_settings
from otelms.domain.entities import Base, Guest, Payment, Reservation, Room, Service
from otelms.scraping.calendar_extract import extract_reservations_from_calendar
from otelms.scraping.folio_extract import extract_guest_data, parse_folio
from otelms.scraping.room_extract import extract_room_number, extract_room_prices, extract_room_type
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


def _as_datetime(value: object) -> datetime | None:
    """Normaliza a datetime lo que venga del calendario.

    extract_reservations_from_calendar puede devolver la fecha ya parseada o
    el texto original según el camino que tomara el tooltip, así que aquí se
    acepta cualquiera de los dos y se devuelve None si no es ninguno.
    """
    return value if isinstance(value, datetime) else None


def _money(value: object) -> Decimal:
    """Convierte a Decimal lo que venga del folio.

    Las columnas de Service y Payment son Numeric: asignarles un float
    arrastraría la representación binaria (0.1 -> 0.1000000000000000055).
    """
    return Decimal(str(value or 0))


class CalendarSyncService:
    """Orquesta la extracción completa de OtelMS y persistencia en BD.

    Extrae:
    - Reservas (calendar → tooltips)
    - Guests (folio form → labels rusos)
    - Services/Charges (folio tables)
    - Payments (folio tables)
    """

    def __init__(self, db: Session, hotel_id: str, otelms_session: requests.Session):
        self.db = db
        self.hotel_id = str(hotel_id)
        self.session = otelms_session
        self.settings = get_settings()

    @classmethod
    def from_login(cls, db: Session, hotel_id: str) -> "CalendarSyncService":
        """Crea service y loguea automáticamente."""
        inst = cls.__new__(cls)
        inst.db = db
        inst.hotel_id = str(hotel_id)
        inst.settings = get_settings()
        inst.session = cls._login(inst.settings, hotel_id)
        return inst

    @staticmethod
    def _login(settings: Settings, hotel_id: str) -> requests.Session:
        """Login HTTP sync.

        verify_ssl se controla via setting `scraper_verify_ssl` (default True).
        En entornos con SSL interception corporativo, se puede desactivar via .env.
        """
        session = requests.Session()
        session.headers.update({
            "User-Agent": settings.browser_user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        session.verify = settings.scraper_verify_ssl

        base = "https://desktop.otelms.com"

        session.get(f"{base}/login_c2/single_login?hmsid={hotel_id}", timeout=15)
        r = session.post(
            f"{base}/login_c2/do_single_login",
            data={"hotel": hotel_id, "login": settings.otelms_default_username,
                  "password": settings.otelms_default_password, "action": "login"},
            headers={"Referer": f"{base}/login_c2/single_login?hmsid={hotel_id}"},
            timeout=15,
        )
        if "reservation_c2/calendar" not in r.text:
            raise RuntimeError("Login fallido")
        logger.info("Login OtelMS exitoso")
        return session

    def sync_all(self) -> dict:
        """Sync completo: calendar → folios → BD. Todo sync."""
        # Calendar
        cal_resp = self.session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
        reservations = extract_reservations_from_calendar(cal_resp.text)
        logger.info(f"Extracted {len(reservations)} reservations")

        stats = {"reservations": 0, "guests": 0, "services": 0, "payments": 0, "errors": 0}

        for res in reservations:
            try:
                # 1. Folio → extract room_type + room_number + guest + services
                fol_resp = self.session.get(
                    f"https://desktop.otelms.com/reservation_c2/folio/{res['resid']}",
                    timeout=20,
                )
                if fol_resp.status_code == 200:
                    folio = parse_folio(fol_resp.text, str(res["resid"]))

                    # Extract + persist room_type + room_number
                    room_type = extract_room_type(fol_resp.text)
                    room_number = extract_room_number(fol_resp.text)
                    if room_type or room_number:
                        self._upsert_room(room_type, room_number, fol_resp.text)
                        if room_number:
                            res["room_number"] = room_number

                    # Upsert reservation (with room_number resolved)
                    self._upsert_reservation(res)
                    stats["reservations"] += 1

                    # Extract + persist guest
                    guest_data = extract_guest_data(fol_resp.text)
                    if guest_data:
                        self._upsert_guest(res["resid"], guest_data)
                        stats["guests"] += 1

                    # Persist services
                    for svc in folio["services"]:
                        self._upsert_service(res["resid"], "folio", svc)
                        stats["services"] += 1

                    # Persist room charges (also as services) with prices
                    for charge in folio["room_charges"]:
                        self._upsert_service(res["resid"], "room_charge", charge)
                        stats["services"] += 1

                    # Extract room prices as services
                    room_prices = extract_room_prices(fol_resp.text)
                    for price in room_prices:
                        self._upsert_service(res["resid"], "room_price", {
                            "name": f"Room rate ({room_type or 'Unknown'})",
                            "legal_entity": "Hotel",
                            "quantity": 1,
                            "price": None,
                            "amount": price["price"],
                            "date": price["date"],
                            "description": price["description"],
                        })
                        stats["services"] += 1

                    # Persist payments
                    for pay in folio["payments"]:
                        self._upsert_payment(res["resid"], pay)
                        stats["payments"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error res {res.get('resid')}: {e}")

        self.db.commit()
        return stats

    def _upsert_reservation(self, res: dict) -> None:
        sync_hash = hashlib.sha256(json.dumps(res, sort_keys=True, default=str).encode()).hexdigest()[:64]
        existing = self.db.get(Reservation, str(res["resid"]))

        # Priority: calendar room_id (from td.calendar_td) > folio room_number
        room_id = "room_default"
        cal_room_id = res.get("room_id")
        room_number = res.get("room_number")

        if cal_room_id:
            # Calendar room_id is the internal room ID from the td cell
            room = self.db.get(Room, str(cal_room_id))
            if room and room.hotel_id == self.hotel_id:
                room_id = str(cal_room_id)
        if room_id == "room_default" and room_number:
            room = self.db.execute(
                select(Room).where(Room.name == room_number, Room.hotel_id == self.hotel_id)
            ).scalar_one_or_none()
            if room:
                room_id = room.id

        if existing:
            if existing.sync_hash == sync_hash:
                return  # no changes
            existing.sync_hash = sync_hash
        else:
            existing = Reservation(
                id=str(res["resid"]),
                hotel_id=self.hotel_id,
                room_id=room_id,
            )
            self.db.add(existing)

        # Actualizar room_id tanto para nuevas como para existentes reservas
        existing.room_id = room_id

        # check_in/check_out ya vienen parseados como datetime de extract_reservations_from_calendar.
        # _as_datetime cubre el caso datetime; _parse_date el string. El plugin de
        # SQLAlchemy tipa la columna como SQLCoreOperations[datetime] y rechaza
        # datetime | None; el valor runtime es nullable, así que el cast es seguro.
        existing.check_in = cast(datetime, _as_datetime(res.get("check_in")) or self._parse_date(res.get("check_in") or ""))
        existing.check_out = cast(datetime, _as_datetime(res.get("check_out")) or self._parse_date(res.get("check_out") or ""))
        existing.status = res.get("status", 1)
        existing.adults = res.get("guest_count") or 1
        existing.source = res.get("channel", "")
        existing.notes = res.get("comments", "")
        existing.sync_hash = sync_hash
        existing.last_synced_at = datetime.utcnow()
        self.db.merge(existing)

    def _upsert_guest(self, reservation_id: str, data: dict) -> None:
        # Derive guest_id from reservation + name hash (unique per reservation)
        name_key = f"{reservation_id}_{data.get('first_name', '')}_{data.get('last_name', '')}"
        guest_id = f"guest_{hashlib.sha256(name_key.encode()).hexdigest()[:12]}"

        existing = self.db.get(Guest, guest_id)
        if not existing:
            existing = Guest(
                id=guest_id,
                hotel_id=self.hotel_id,
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                middle_name=data.get("middle_name"),
                gender=data.get("gender"),
                birth_date=self._parse_date(data.get("birth_date", "")),
                email=data.get("email"),
                phone=data.get("phone"),
                nationality=data.get("country"),
                city=data.get("city"),
            )
            self.db.add(existing)
        else:
            existing.first_name = data.get("first_name", existing.first_name)
            existing.last_name = data.get("last_name", existing.last_name)
            existing.email = data.get("email", existing.email)
            existing.phone = data.get("phone", existing.phone)

    def _upsert_service(self, reservation_id: str, svc_type: str, svc_data: dict) -> None:
        svc_id = f"svc_{reservation_id}_{svc_type}_{svc_data.get('id', hash(str(svc_data)))}"
        existing = self.db.get(Service, svc_id)

        date_val = self._parse_date(svc_data.get("date", "")) or datetime.utcnow()

        if not existing:
            svc = Service(
                id=svc_id,
                reservation_id=reservation_id,
                date=date_val,
                title=svc_data.get("name", svc_data.get("description", "")),
                description=svc_data.get("legal_entity", ""),
                quantity=_money(svc_data.get("quantity")) or Decimal("1"),
                price=_money(svc_data.get("price")),
                total=_money(svc_data.get("amount")),
                legal_entity=svc_data.get("legal_entity", ""),
            )
            self.db.add(svc)
        else:
            existing.quantity = _money(svc_data.get("quantity")) or Decimal("1")
            existing.total = _money(svc_data.get("amount"))

    def _upsert_payment(self, reservation_id: str, pay_data: dict) -> None:
        pay_id = f"pay_{reservation_id}_{pay_data.get('invoice_num', hash(str(pay_data)))}"
        existing = self.db.get(Payment, pay_id)

        date_val = self._parse_date(pay_data.get("date", "")) or datetime.utcnow()

        if not existing:
            pay = Payment(
                id=pay_id,
                reservation_id=reservation_id,
                date=date_val,
                amount=_money(pay_data.get("amount")),
                method=pay_data.get("payment_type", ""),
                reference=pay_data.get("invoice_num", ""),
                status=pay_data.get("card_status", ""),
                card_number=pay_data.get("card_number", ""),
            )
            self.db.add(pay)
        else:
            existing.amount = _money(pay_data.get("amount"))

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.strip())
        except (ValueError, TypeError):
            return None

    def _upsert_room(self, room_type: str | None, room_number: str | None, folio_html: str) -> None:
        """Persista habitación con número real + tipo.

        OtelMS usa room CATEGORIES (Matrimonial, Triple) no room numbers.
        El room_number (ej: '201') se extrae del folio tooltip.
        Se persiste en `rooms` con name=room_number.

        Primero busca por name+hotel_id; si existe, actualiza ese mismo registro
        en vez de crear uno nuevo con id `room_{number}` (que generaría duplicados).
        """
        if not room_number:
            return

        existing = self.db.execute(
            select(Room).where(
                Room.name == room_number,
                Room.hotel_id == self.hotel_id,
            )
        ).scalar_one_or_none()

        if existing:
            if room_type:
                cat_id = room_type.lower().replace(" ", "_")
                if existing.category_id != cat_id:
                    existing.category_id = cat_id
            return

        room_id = room_number
        room = Room(
            id=room_id,
            hotel_id=self.hotel_id,
            category_id=room_type.lower().replace(" ", "_") if room_type else None,
            name=room_number,
            max_occupancy=2,
            is_active=True,
        )
        self.db.add(room)

    @staticmethod
    def get_db_session(db_url: str) -> Session:
        """Crea una DB session sync."""
        if "+aiosqlite" in db_url:
            db_url = db_url.replace("+aiosqlite", "")
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()
