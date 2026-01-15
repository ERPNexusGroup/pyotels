from datetime import date, datetime
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field, field_validator

# --- Shared / Common Models ---

class RoomCategory(BaseModel):
    id: str
    name: str
    rooms: List[Dict[str, Any]]

# --- Calendar Grid Models ---

class ReservationData(BaseModel):
    """Datos de una celda específica en el calendario (Grid)"""
    date: str 
    room_id: str
    room_number: str
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    status: str
    availability: int
    day_id: str
    reservation_status: Optional[str] = None
    details_reservation: Dict[str, Any] = Field(default_factory=dict)
    reservation_id: Optional[str] = None
    guest_name: Optional[str] = None
    source: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    balance: Optional[str] = None

class CalendarGrid(BaseModel):
    """Respuesta para la petición de Reservaciones/Grid"""
    reservation_data: List[ReservationData]
    date_range: Dict[str, Any]
    extracted_at: str # Changed to str to avoid serialization errors
    day_id_to_date: Dict[str, str] = Field(default_factory=dict)

class CalendarCategories(BaseModel):
    """Respuesta para la petición de Categorías"""
    categories: List[RoomCategory]
    extracted_at: str

# --- Folio / Detail Models ---

class Guest(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    id: Optional[str] = None
    dob: Optional[str] = None

class Service(BaseModel):
    date: Optional[str] = None
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    price: float
    quantity: float
    total: Optional[float] = None
    entity: Optional[str] = None

class PaymentTransaction(BaseModel):
    date: str
    created: str
    id: str
    amount: str
    method: str

class Note(BaseModel):
    date: str
    author: str
    message: str
    type: str = "note"

class Car(BaseModel):
    brand: str
    model: str
    color: str
    plate: str

class DailyTariff(BaseModel):
    date: str
    rate_type: str
    price: float

class ChangeLog(BaseModel):
    date: str
    log_id: str
    user: str
    type: str
    action: str
    amount: str
    description: str

class Card(BaseModel):
    number: str
    holder: str
    expiration: str

class ReservationDetail(BaseModel):
    """Respuesta para la petición de Detalle de Reserva"""
    reservation_id: str
    guests: List[Guest] = Field(default_factory=list)
    services: List[Service] = Field(default_factory=list)
    payments: List[PaymentTransaction] = Field(default_factory=list)
    cars: List[Car] = Field(default_factory=list)
    notes: List[Note] = Field(default_factory=list)
    daily_tariffs: List[DailyTariff] = Field(default_factory=list)
    logs: List[ChangeLog] = Field(default_factory=list)
    cards: List[Card] = Field(default_factory=list)
    
    balance: float = 0.0
    total_price: float = 0.0
    
    channel_info: Dict[str, Any] = Field(default_factory=dict)
    basic_info: Dict[str, Any] = Field(default_factory=dict)
    
    raw_html: Optional[str] = None
    
    # Compatibility fields
    room_number: Optional[str] = None
    room_id: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    status: Optional[str] = None
    raw_form_data: Dict[str, Any] = Field(default_factory=dict)

# --- Legacy / Internal ---
class CalendarData(BaseModel):
    """Modelo interno completo (opcional, si se necesita todo junto)"""
    categories: List[RoomCategory]
    reservation_data: List[ReservationData]
    date_range: Dict[str, Any]
    extracted_at: str
    day_id_to_date: Dict[str, str] = Field(default_factory=dict)
