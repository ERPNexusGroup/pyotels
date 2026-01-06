from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from tortoise import fields, models

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
class CalendarData:
    """Representa todos los datos extraídos del calendario."""
    categories: List[RoomCategory]
    reservation_data: List[ReservationData]
    date_range: Dict[str, str]
    extracted_at: str

class Reservation(models.Model):
    """Modelo de base de datos para las reservas."""
    id = fields.IntField(pk=True)
    reservation_id = fields.CharField(max_length=50, null=True, index=True)
    room_number = fields.CharField(max_length=20)
    guest_name = fields.CharField(max_length=255, null=True)
    check_in = fields.DateField(null=True)
    check_out = fields.DateField(null=True)
    status = fields.CharField(max_length=50)
    source = fields.CharField(max_length=100, null=True)
    price = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "reservations"

    def __str__(self):
        return f"Reserva {self.reservation_id} - {self.guest_name}"
