"""
Servicio para sincronizar configuración maestra desde OtelMS a la base de datos local.
Asegura que el hotel, categorías, habitaciones, métodos de pago y canales
estén sincronizados con la realidad de OtelMS antes de procesar reservas.
"""
from datetime import UTC, datetime
import hashlib
from typing import Any
from sqlalchemy import select

from otelms.config.settings import settings
from otelms.utils.crypto import CredentialEncryption
from otelms.domain.entities import (
    Category,
    Dealer,
    Hotel,
    PaymentMethod,
    PropertyService,
    Room,
)
from otelms.domain.repositories.database import get_db_session
from otelms.scraping.setup_extract import SetupExtractor
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class SetupSyncService:
    """Sincroniza el catálogo maestro del hotel único (18330) en base de datos."""

    def __init__(self, hotel_id: str | None = None):
        self.hotel_id = hotel_id or settings.otelms_default_hotel_id

    async def sync_all_setup(self) -> dict[str, Any]:
        """Extrae de OtelMS y persiste en base de datos toda la configuración maestra."""
        logger.info("Starting setup synchronization", hotel_id=self.hotel_id)
        async with SetupExtractor(self.hotel_id) as extractor:
            setup_data = await extractor.extract_all_setup()

        async with get_db_session() as session:
            # 1. Sincronizar Hotel / Propiedad
            hotel_info = setup_data.get("hotel", {})
            res_hotel = await session.execute(select(Hotel).where(Hotel.id == self.hotel_id))
            hotel = res_hotel.scalar_one_or_none()
            if hotel:
                hotel.name = hotel_info.get("name") or hotel.name
                hotel.legal_name = hotel_info.get("legal_name")
                hotel.property_type = hotel_info.get("property_type")
                hotel.street = hotel_info.get("street")
                hotel.city = hotel_info.get("city")
                hotel.state = hotel_info.get("state")
                hotel.country = hotel_info.get("country")
                hotel.post_code = hotel_info.get("post_code")
                hotel.gps_coordinates = hotel_info.get("gps_coordinates")
                hotel.phone = hotel_info.get("reception_phone")
                hotel.email = hotel_info.get("email")
                hotel.web_address = hotel_info.get("web_address")
                hotel.star_rating = hotel_info.get("star_rating")
                hotel.check_in_time = hotel_info.get("check_in_time")
                hotel.check_out_time = hotel_info.get("check_out_time")
                hotel.timezone = hotel_info.get("timezone")
                hotel.last_sync_at = datetime.now(UTC)
            else:
                raw_pw = settings.otelms_default_password or ""
                enc_pw = CredentialEncryption().encrypt(raw_pw) if raw_pw else None
                pw_hash = hashlib.sha256(raw_pw.encode("utf-8")).hexdigest() if raw_pw else ""
                hotel = Hotel(
                    id=self.hotel_id,
                    name=hotel_info.get("name") or f"Hotel {self.hotel_id}",
                    domain=settings.otelms_base_domain,
                    username=settings.otelms_default_username or "",
                    password_hash=pw_hash,
                    encrypted_password=enc_pw,
                    is_active=True,
                    legal_name=hotel_info.get("legal_name"),
                    property_type=hotel_info.get("property_type"),
                    street=hotel_info.get("street"),
                    city=hotel_info.get("city"),
                    state=hotel_info.get("state"),
                    country=hotel_info.get("country"),
                    post_code=hotel_info.get("post_code"),
                    gps_coordinates=hotel_info.get("gps_coordinates"),
                    phone=hotel_info.get("reception_phone"),
                    email=hotel_info.get("email"),
                    web_address=hotel_info.get("web_address"),
                    star_rating=hotel_info.get("star_rating"),
                    check_in_time=hotel_info.get("check_in_time"),
                    check_out_time=hotel_info.get("check_out_time"),
                    timezone=hotel_info.get("timezone"),
                    last_sync_at=datetime.now(UTC),
                )
                session.add(hotel)
            await session.flush()

            # 2. Sincronizar Categorías
            cat_map: dict[str, str] = {}
            for cat_data in setup_data.get("categories", []):
                cat_id = str(cat_data["id"])
                cat_map[cat_data["name"]] = cat_id
                res_c = await session.execute(
                    select(Category).where(Category.hotel_id == self.hotel_id, Category.id == cat_id)
                )
                cat = res_c.scalar_one_or_none()
                if cat:
                    cat.name = cat_data["name"]
                    cat.sort_order = cat_data.get("sort_order", 0)
                else:
                    cat = Category(
                        id=cat_id,
                        hotel_id=self.hotel_id,
                        name=cat_data["name"],
                        sort_order=cat_data.get("sort_order", 0),
                    )
                    session.add(cat)

            await session.flush()

            # 3. Sincronizar Habitaciones
            for room_data in setup_data.get("rooms", []):
                room_id = str(room_data["id"])
                cat_name = room_data.get("category_name", "")
                cat_id = cat_map.get(cat_name)

                res_r = await session.execute(
                    select(Room).where(Room.hotel_id == self.hotel_id, Room.id == room_id)
                )
                room = res_r.scalar_one_or_none()
                if room:
                    room.name = room_data["name"]
                    room.floor = room_data.get("floor")
                    if cat_id:
                        room.category_id = cat_id
                else:
                    room = Room(
                        id=room_id,
                        hotel_id=self.hotel_id,
                        name=room_data["name"],
                        category_id=cat_id,
                        floor=room_data.get("floor"),
                        is_active=True,
                    )
                    session.add(room)

            # 4. Sincronizar Métodos de Pago
            for pm_data in setup_data.get("payment_methods", []):
                pm_id = str(pm_data["id"])
                res_pm = await session.execute(
                    select(PaymentMethod).where(PaymentMethod.hotel_id == self.hotel_id, PaymentMethod.id == pm_id)
                )
                pm = res_pm.scalar_one_or_none()
                if pm:
                    pm.name = pm_data["name"]
                    pm.type = pm_data.get("type")
                else:
                    pm = PaymentMethod(
                        id=pm_id,
                        hotel_id=self.hotel_id,
                        name=pm_data["name"],
                        type=pm_data.get("type"),
                        is_active=True,
                    )
                    session.add(pm)

            # 5. Sincronizar Canales / Dealers
            for d_data in setup_data.get("dealers", []):
                d_id = str(d_data["id"])
                res_d = await session.execute(
                    select(Dealer).where(Dealer.hotel_id == self.hotel_id, Dealer.id == d_id)
                )
                dealer = res_d.scalar_one_or_none()
                if dealer:
                    dealer.name = d_data["name"]
                    dealer.phone = d_data.get("phone")
                    dealer.address = d_data.get("address")
                else:
                    dealer = Dealer(
                        id=d_id,
                        hotel_id=self.hotel_id,
                        name=d_data["name"],
                        phone=d_data.get("phone"),
                        address=d_data.get("address"),
                        is_active=True,
                    )
                    session.add(dealer)

            # 6. Sincronizar Servicios / Amenidades
            services_catalog = setup_data.get("services_catalog", {}).get("active_services", [])
            for s_idx, s_data in enumerate(services_catalog):
                s_id = str(s_idx + 1)
                res_s = await session.execute(
                    select(PropertyService).where(PropertyService.hotel_id == self.hotel_id, PropertyService.id == s_id)
                )
                ps = res_s.scalar_one_or_none()
                if ps:
                    ps.name = s_data.get("name") or s_id
                    ps.label = s_data.get("label") or s_id
                else:
                    ps = PropertyService(
                        id=s_id,
                        hotel_id=self.hotel_id,
                        name=s_data.get("name") or s_id,
                        label=s_data.get("label") or s_id,
                        is_active=True,
                    )
                    session.add(ps)

            await session.commit()

        logger.info(
            "Setup synchronization completed successfully",
            hotel_id=self.hotel_id,
            categories=len(setup_data.get("categories", [])),
            rooms=len(setup_data.get("rooms", [])),
            payment_methods=len(setup_data.get("payment_methods", [])),
            dealers=len(setup_data.get("dealers", [])),
        )
        return {
            "success": True,
            "hotel_id": self.hotel_id,
            "hotel_name": hotel_info.get("name"),
            "categories_synced": len(setup_data.get("categories", [])),
            "rooms_synced": len(setup_data.get("rooms", [])),
            "payment_methods_synced": len(setup_data.get("payment_methods", [])),
            "dealers_synced": len(setup_data.get("dealers", [])),
        }

    sync_all = sync_all_setup
