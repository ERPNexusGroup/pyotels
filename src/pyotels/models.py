from datetime import datetime
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

# --- Shared / Common Models ---

class RoomCategory(BaseModel):
    id: str
    name: str
    rooms: List[Dict[str, Any]]

class Guest(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    dob: Optional[str] = None

class Service(BaseModel):
    title: str
    price: float
    quantity: float

class PaymentTransaction(BaseModel):
    date: str
    amount: str
    method: str

class DailyTariff(BaseModel):
    date: str
    rate_type: str
    price: float

# --- Calendar Grid Models ---

class ReservationData(BaseModel):
    """Datos de una celda específica en el calendario (Grid)"""
    # Campos extraídos del tooltip/celda
    reservation_number: Optional[str] = None
    guest_name: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    created_at: Optional[str] = None
    guest_count: Optional[int] = None
    balance: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    user: Optional[str] = None
    comments: Optional[str] = None
    room: Optional[str] = None # Nombre/Número de habitación
    reservation_status: Optional[int] = None # 1: Reservación, 2: Check-in, 3: Check-out
    # Campos de contexto del calendario
    room_id: str
    cell_status: str # occupied, available, locked

class CalendarReservation(BaseModel):
    """Respuesta para la petición de Reservaciones/Grid"""
    reservation_data: List[ReservationData]
    date_range: Dict[str, Any]
    extracted_at: str
    day_id_to_date: Dict[str, str] = Field(default_factory=dict)

class CalendarCategories(BaseModel):
    """Respuesta para la petición de Categorías"""
    categories: List[RoomCategory]

# --- Folio / Detail Models ---

class ReservationDetail(BaseModel):
    """Respuesta para la petición de Detalle de Reserva (Modal)"""
    reservation_number: Optional[str] = None
    guest_name: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    created_at: Optional[str] = None
    guest_count: Optional[int] = None
    balance: Optional[float] = None
    total: Optional[float] = None
    paid: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    user: Optional[str] = None
    comments: Optional[str] = None
    room_type: Optional[str] = None
    room: Optional[str] = None
    rate: Optional[str] = None
    source: Optional[str] = None

# --- Legacy / Internal ---
class CalendarData(BaseModel):
    """Modelo interno completo"""
    categories: List[RoomCategory]
    reservation_data: List[ReservationData]
    date_range: Dict[str, Any]
    extracted_at: str
    day_id_to_date: Dict[str, str] = Field(default_factory=dict)
