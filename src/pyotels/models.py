from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class RoomCategory:
    """Representa una categoría de habitaciones."""
    id: str
    name: str
    rooms: List[Dict[str, Any]]

@dataclass
class ReservationData:
    """Representa los datos de una habitación en una fecha específica."""
    date: str
    room_id: str
    room_number: str
    category_id: str
    category_name: str
    status: str  # 'available', 'occupied', 'locked'
    availability: int
    day_id: str
    reservation_status: Optional[str] = None
    details_reservation: Dict[str, Any] = field(default_factory=dict)
    reservation_id: Optional[str] = None
    guest_name: Optional[str] = None
    source: Optional[str] = None  # Booking, Venta directa, etc.
    check_in: Optional[str] = None  # Fecha de llegada
    check_out: Optional[str] = None  # Fecha de salida
    balance: Optional[str] = None

@dataclass
class Guest:
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    id: Optional[str] = None

@dataclass
class Service:
    date: str
    title: str
    description: str
    price: float
    quantity: int
    total: float

@dataclass
class Payment:
    date: str
    amount: float
    type: str
    method: str
    description: Optional[str] = None

@dataclass
class Note:
    date: str
    author: str
    message: str
    type: str = "note"

@dataclass
class Car:
    brand: str
    model: str
    color: str
    plate: str

@dataclass
class DailyTariff:
    date: str
    rate_type: str
    price: float

@dataclass
class ChangeLog:
    date: str
    log_id: str
    user: str
    type: str
    action: str
    amount: str
    description: str

@dataclass
class Card:
    number: str
    holder: str
    expiration: str

@dataclass
class ReservationDetail:
    """Representa los detalles completos de una reserva."""
    reservation_id: str
    guests: List[Guest]
    services: List[Service]
    payments: List[Payment]
    cars: List[Car]
    notes: List[Note]
    daily_tariffs: List[DailyTariff]
    logs: List[ChangeLog]
    cards: List[Card]
    balance: float
    total_price: float
    channel_info: Dict[str, Any]
    # Basic info fields for the main Reservation model
    basic_info: Dict[str, Any]
    raw_html: Optional[str] = None

@dataclass
class CalendarData:
    """Representa todos los datos extraídos del calendario."""
    categories: List[RoomCategory]
    reservation_data: List[ReservationData]
    date_range: Dict[str, str]
    extracted_at: str
