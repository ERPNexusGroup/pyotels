"""
Modelos de base de datos (SQLAlchemy 2.x) - Persistencia.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
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


class SyncLog(Base):
    """Log de sincronizaciones."""
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
