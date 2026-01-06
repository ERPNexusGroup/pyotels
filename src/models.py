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
    detail_url: Optional[str] = None
    reservation_id: Optional[str] = None
    guest_name: Optional[str] = None
    source: Optional[str] = None  # Booking, Venta directa, etc.
    check_in: Optional[str] = None  # Fecha de llegada
    check_out: Optional[str] = None  # Fecha de salida
    balance: Optional[str] = None

@dataclass
class Guest:
    """Representa un huésped."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None

@dataclass
class Reservation:
    """Representa una reserva completa."""
    id: str # ID único de la reserva en el sistema
    room_number: str
    check_in: str
    check_out: str
    status: str
    total_price: Optional[float] = None
    currency: Optional[str] = None
    source: Optional[str] = None # Booking, Expedia, Directo, etc.
    main_guest: Optional[Guest] = None
    companions: List[Guest] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict) # Para guardar otros datos no estructurados

@dataclass
class CalendarData:
    """Representa todos los datos extraídos del calendario."""
    categories: List[RoomCategory]
    reservation_data: List[ReservationData]
    date_range: Dict[str, str]
    extracted_at: str
