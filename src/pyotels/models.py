from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field


# --- Model Reservation Details ---

class RoomCategory(BaseModel):
    id: str
    name: str
    rooms: List[Dict[str, Any]]


class Guest(BaseModel):
    id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    street: Optional[str] = None
    house: Optional[str] = None
    zip_code: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    issue_date: Optional[str] = None
    expiration_date: Optional[str] = None
    issued_by: Optional[str] = None
    name: Optional[str] = None # Full name


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
    room: Optional[str] = None  # Nombre/Número de habitación
    reservation_status: Optional[int] = None  # 1: Reservación, 2: Check-in, 3: Check-out
    # Campos de contexto del calendario
    room_id: str
    cell_status: str  # occupied, available, locked


class ReservationDetail(BaseModel):
    guest: Guest

# --------------------------------------------------------------------------------------

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

class ReservationModalDetail(BaseModel):
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
