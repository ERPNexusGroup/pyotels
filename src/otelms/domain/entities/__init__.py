"""
Modelos de base de datos (SQLAlchemy 2.x) - Persistencia.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Current UTC datetime for default values."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos."""
    pass


class Hotel(Base):
    """Hotel configurado en el sistema."""
    __tablename__ = "hotels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str] = mapped_column(String(255), default="otelms.com")
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # Hashed
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet encrypted
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Scraper configuration per hotel
    scraper_rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=30)
    scraper_burst: Mapped[int] = mapped_column(Integer, default=5)
    scraper_timeout_ms: Mapped[int] = mapped_column(Integer, default=60000)
    scraper_navigation_timeout_ms: Mapped[int] = mapped_column(Integer, default=45000)
    scraper_selector_timeout_ms: Mapped[int] = mapped_column(Integer, default=20000)
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    use_custom_domain: Mapped[bool] = mapped_column(default=False)
    scraper_headless: Mapped[bool] = mapped_column(default=True)

    # Relaciones
    categories: Mapped[list["Category"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    rooms: Mapped[list["Room"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    guests: Mapped[list["Guest"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    sync_logs: Mapped[list["SyncLog"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    room_availability: Mapped[list["RoomAvailability"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    dealers: Mapped[list["Dealer"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    payment_methods: Mapped[list["PaymentMethod"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")
    property_services: Mapped[list["PropertyService"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")

    # Datos maestros de la propiedad (/setup_property_c2/property_information)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    web_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    post_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gps_coordinates: Mapped[str | None] = mapped_column(String(100), nullable=True)
    star_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_in_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    check_out_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_hotels_is_active", "is_active"),
    )


class Category(Base):
    """Categoría de habitación."""
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="categories")
    rooms: Mapped[list["Room"]] = relationship(back_populates="category", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_categories_hotel_id", "hotel_id"),
        UniqueConstraint("hotel_id", "id", name="uq_category_hotel_id"),
    )


class CategoryAvailability(Base):
    """Habitaciones disponibles de una categoría en una fecha concreta.

    El número lo publica OtelMS en la fila de resumen del calendario
    (`div.calendar_sum`), no se recalcula: el portal retiene habitaciones por
    encima de las ocupadas (una categoría de 12 nunca pasa de 10) y marca 0 en
    días bloqueados aunque queden libres. Contrastar en
    `tests/manual/test_calendar_availability.py`.
    """

    __tablename__ = "category_availability"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    available: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_category_availability_hotel_date", "hotel_id", "date"),
        UniqueConstraint("category_id", "date", name="uq_category_availability_date"),
    )


class Room(Base):
    """Habitación individual."""
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    floor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    max_occupancy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="rooms")
    category: Mapped[Optional["Category"]] = relationship(back_populates="rooms")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="room")

    __table_args__ = (
        Index("ix_rooms_hotel_id", "hotel_id"),
        Index("ix_rooms_category_id", "category_id"),
        Index("ix_rooms_is_active", "is_active"),
        UniqueConstraint("hotel_id", "id", name="uq_room_hotel_id"),
    )


class ChannelRate(Base):
    """Tarifa por canal (OTA / directo) para una categoría y fecha.

    OtelMS publica tarifas distintas según el canal de venta: el folio
    muestra el precio de la reserva, pero no hay una vista separada por
    canal. Esta tabla permite registrar tarifas manuales o provenientes
    de un channel manager externo, indexadas por (hotel, category, rate,
    channel, date).
    """

    __tablename__ = "channel_rates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    rate_id: Mapped[str] = mapped_column(String(16), default="1", nullable=False)  # 1=Standard, 2=Feriados
    channel: Mapped[str] = mapped_column(String(64), nullable=False)  # direct, ota, booking, expedia...
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    min_stay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_channel_rates_hotel_category", "hotel_id", "category_id"),
        Index("ix_channel_rates_date", "date"),
        Index("ix_channel_rates_channel", "channel"),
        UniqueConstraint("hotel_id", "category_id", "rate_id", "channel", "date", name="uq_channel_rate"),
    )


class Dealer(Base):
    """Canal de venta / distribuidor (OTAs, Venta directa, etc.) (/setup_dealers_c2/dealers_list/1)."""
    __tablename__ = "dealers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hotel: Mapped["Hotel"] = relationship(back_populates="dealers")

    __table_args__ = (
        Index("ix_dealers_hotel_id", "hotel_id"),
        UniqueConstraint("hotel_id", "id", name="uq_dealer_hotel_id"),
    )


class PaymentMethod(Base):
    """Método de pago configurado en el hotel (/setup_payment_types_c2/type_list/1)."""
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hotel: Mapped["Hotel"] = relationship(back_populates="payment_methods")

    __table_args__ = (
        Index("ix_payment_methods_hotel_id", "hotel_id"),
        UniqueConstraint("hotel_id", "id", name="uq_payment_method_hotel_id"),
    )


class PropertyService(Base):
    """Servicio / amenidad del catálogo del hotel (/setup_property_c2/property_description)."""
    __tablename__ = "property_services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hotel: Mapped["Hotel"] = relationship(back_populates="property_services")

    __table_args__ = (
        Index("ix_property_services_hotel_id", "hotel_id"),
        UniqueConstraint("hotel_id", "id", name="uq_property_service_hotel_id"),
    )


class Guest(Base):
    """Huésped."""
    __tablename__ = "guests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="guests")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="guest")

    @property
    def full_name(self) -> str:
        """Nombre completo del huésped.

        GuestResponse.full_name es obligatorio y se serializa con
        from_attributes=True, así que la entidad debe exponerlo. Se compone
        solo con columnas ya cargadas: ninguna lectura diferida, que en sesión
        async lanzaría MissingGreenlet.

        OtelMS devuelve los apellidos con espacio inicial (" JOFRE"), así que
        cada parte se normaliza antes de unir.
        """
        parts = (self.first_name, self.middle_name, self.last_name)
        return " ".join(p.strip() for p in parts if p and p.strip())

    __table_args__ = (
        Index("ix_guests_hotel_id", "hotel_id"),
        Index("ix_guests_email", "email"),
        Index("ix_guests_document", "document_type", "document_number"),
        UniqueConstraint("hotel_id", "id", name="uq_guest_hotel_id"),
    )


class ReservationStatusEnum(SQLEnum):
    """Estados de reserva."""
    RESERVATION = 1
    CHECK_IN = 2
    CHECK_OUT = 3
    CANCELLED = 4
    NO_SHOW = 5


class Reservation(Base):
    """Reserva principal."""
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    room_id: Mapped[str] = mapped_column(String(64), ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False)
    guest_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("guests.id", ondelete="SET NULL"), nullable=True)

    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1=Reserva, 2=Check-in, 3=Check-out

    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    babies: Mapped[int] = mapped_column(Integer, default=0)

    total_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Datos adicionales de folio profundo
    vehicle_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_plate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel_reservation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    room_reservation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadatos de sync
    otelms_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otelms_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sync_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Hash para detectar cambios

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="reservations")
    room: Mapped["Room"] = relationship(back_populates="reservations")
    guest: Mapped[Optional["Guest"]] = relationship(back_populates="reservations")
    services: Mapped[list["Service"]] = relationship(back_populates="reservation", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="reservation", cascade="all, delete-orphan")
    night_rates: Mapped[list["ReservationNightRate"]] = relationship(back_populates="reservation", cascade="all, delete-orphan")
    change_history: Mapped[list["ReservationChangeHistory"]] = relationship(back_populates="reservation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_reservations_hotel_id", "hotel_id"),
        Index("ix_reservations_room_id", "room_id"),
        Index("ix_reservations_guest_id", "guest_id"),
        Index("ix_reservations_check_in", "check_in"),
        Index("ix_reservations_check_out", "check_out"),
        Index("ix_reservations_status", "status"),
        Index("ix_reservations_dates_status", "check_in", "check_out", "status"),
        Index("ix_reservations_last_synced", "last_synced_at"),
        UniqueConstraint("hotel_id", "id", name="uq_reservation_hotel_id"),
    )


class Service(Base):
    """Servicio/consumo en una reserva."""
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1"))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    legal_entity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    reservation: Mapped["Reservation"] = relationship(back_populates="services")

    __table_args__ = (
        Index("ix_services_reservation_id", "reservation_id"),
        Index("ix_services_date", "date"),
        UniqueConstraint("reservation_id", "id", name="uq_service_reservation_id"),
    )


class Payment(Base):
    """Pago de una reserva."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Últimos 4 dígitos
    card_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    reservation: Mapped["Reservation"] = relationship(back_populates="payments")

    __table_args__ = (
        Index("ix_payments_reservation_id", "reservation_id"),
        Index("ix_payments_date", "date"),
        UniqueConstraint("reservation_id", "id", name="uq_payment_reservation_id"),
    )


class ReservationNightRate(Base):
    """Tarifa diaria asignada por cada noche de la reserva (/folio/{id}/1 tabla 7)."""
    __tablename__ = "reservation_night_rates"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    rate_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reservation: Mapped["Reservation"] = relationship(back_populates="night_rates")

    __table_args__ = (
        Index("ix_reservation_night_rates_res_date", "reservation_id", "date"),
        UniqueConstraint("reservation_id", "date", name="uq_res_night_rate_date"),
    )


class ReservationChangeHistory(Base):
    """Log de auditoría e historial de cambios de la reserva (/folio/{id}/1 tabla 9)."""
    __tablename__ = "reservation_change_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reservation: Mapped["Reservation"] = relationship(back_populates="change_history")

    __table_args__ = (
        Index("ix_reservation_history_res_id", "reservation_id"),
        Index("ix_reservation_history_date", "date"),
    )


class SyncLog(Base):
    """Log de sincronizaciones."""
    __tablename__ = "sync_logs"

    # SQLite solo autoincrementa con INTEGER PRIMARY KEY (BIGINT NO genera IDs)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)  # calendar, categories, full, detail
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # started, completed, failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array de errores
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="sync_logs")

    __table_args__ = (
        Index("ix_sync_logs_hotel_id", "hotel_id"),
        Index("ix_sync_logs_sync_type", "sync_type"),
        Index("ix_sync_logs_status", "status"),
        Index("ix_sync_logs_started_at", "started_at"),
    )


class ApiKey(Base):
    """API Keys para autenticación."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # Hashed
    is_active: Mapped[bool] = mapped_column(default=True)
    rate_limit: Mapped[int] = mapped_column(Integer, default=60)  # requests per minute
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_api_keys_is_active", "is_active"),
    )


class RoomAvailability(Base):
    """Disponibilidad/bloqueo de habitaciones por rango de fechas.

    Permite cerrar (bloquear) o abrir (desbloquear) habitaciones específicas
    o todas las habitaciones de un hotel (room_id = NULL) para un rango de fechas.
    """

    __tablename__ = "room_availability"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_blocked: Mapped[bool] = mapped_column(default=True)  # True = cerrada/no disponible, False = abierta/disponible
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # ej: "maintenance", "renovation", "private_event"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    hotel: Mapped["Hotel"] = relationship(back_populates="room_availability")
    room: Mapped[Optional["Room"]] = relationship()

    __table_args__ = (
        Index("ix_room_availability_hotel_id", "hotel_id"),
        Index("ix_room_availability_room_id", "room_id"),
        Index("ix_room_availability_dates", "start_date", "end_date"),
        Index("ix_room_availability_is_blocked", "is_blocked"),
    )


# ============================================================
# Roles y permisos (para control de acceso a endpoints)
# ============================================================

class Permission(str, Enum):
    """Permisos del sistema. Cada endpoint puede requerir uno o más."""
    HOUSEKEEPING_READ = "housekeeping:read"
    HOUSEKEEPING_WRITE = "housekeeping:write"
    RESERVATIONS_READ = "reservations:read"
    RESERVATIONS_WRITE = "reservations:write"
    REPORTS_READ = "reports:read"
    REPORTS_WRITE = "reports:write"
    ADMIN_READ = "admin:read"
    ADMIN_WRITE = "admin:write"
    SCRAPING_MANAGE = "scraping:manage"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"


class Role(Base):
    """Rol de usuario con conjunto de permisos."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[list[str]] = mapped_column(
        Text, nullable=False, default="[]"
    )  # JSON array de Permission values
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_roles_name", "name"),
        Index("ix_roles_is_active", "is_active"),
    )


class ApiKeyRole(Base):
    """Relación many-to-many entre API keys y roles."""

    __tablename__ = "api_key_roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_key_id: Mapped[str] = mapped_column(String(64), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(64), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("api_key_id", "role_id", name="uq_api_key_role"),
        Index("ix_api_key_roles_api_key_id", "api_key_id"),
        Index("ix_api_key_roles_role_id", "role_id"),
    )


# ============================================================
# Housekeeping status (seguimiento de limpieza por habitación/fecha)
# ============================================================

class HousekeepingStatus(Base):
    """Estado de limpieza de una habitación para una fecha concreta.

    Estados:
    - 0 = pending (pendiente)
    - 1 = in_progress (en proceso)
    - 2 = cleaned (limpia)

    Una vez marcada como limpia (status=2), la habitación no vuelve a aparecer
    en el listado de pendientes del endpoint GET /housekeeping para esa fecha.
    """

    __tablename__ = "housekeeping_status"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False)
    room_id: Mapped[str] = mapped_column(String(64), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0=pending, 1=in_progress, 2=cleaned
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)  # quién cambió el estado
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("hotel_id", "room_id", "date", name="uq_housekeeping_status_room_date"),
        Index("ix_housekeeping_status_hotel_date", "hotel_id", "date"),
        Index("ix_housekeeping_status_room_id", "room_id"),
        Index("ix_housekeeping_status_status", "status"),
    )
