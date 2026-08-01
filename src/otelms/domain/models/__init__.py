"""
Modelos de dominio (Pydantic) - Contratos de la API.
Estos modelos definen la forma de los datos que expone la API.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


class HotelBase(BaseModel):
    """Base para hotel."""
    id: str = Field(..., description="ID único del hotel en OtelMS")
    name: Optional[str] = Field(None, description="Nombre del hotel")
    domain: str = Field(default="otelms.com", description="Dominio base")


class HotelCreate(HotelBase):
    """Para crear hotel."""
    username: str = Field(..., description="Usuario de acceso")
    password: str = Field(..., description="Contraseña de acceso")


class HotelResponse(HotelBase):
    """Respuesta de hotel."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: Optional[str] = None
    domain: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    last_sync_at: Optional[datetime] = None


class CategoryBase(BaseModel):
    """Base para categoría de habitación."""
    id: str = Field(..., description="ID de la categoría")
    name: str = Field(..., description="Nombre de la categoría")


class CategoryResponse(CategoryBase):
    """Respuesta de categoría con habitaciones."""
    model_config = ConfigDict(from_attributes=True)

    rooms: list["RoomResponse"] = []


class RoomBase(BaseModel):
    """Base para habitación."""
    id: str = Field(..., description="ID de la habitación")
    name: str = Field(..., description="Nombre/Número de la habitación")
    category_id: str = Field(..., description="ID de la categoría")


class RoomResponse(RoomBase):
    """Respuesta de habitación."""
    model_config = ConfigDict(from_attributes=True)

    category: Optional[CategoryResponse] = None
    floor: Optional[str] = None
    max_occupancy: Optional[int] = None


class GuestBase(BaseModel):
    """Base para huésped."""
    id: Optional[str] = Field(None, description="ID del huésped en OtelMS")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    nationality: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class GuestResponse(GuestBase):
    """Respuesta de huésped."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    created_at: datetime
    updated_at: datetime


class ReservationBase(BaseModel):
    """Base para reserva."""
    id: str = Field(..., description="ID de la reserva en OtelMS")
    hotel_id: str = Field(..., description="ID del hotel")
    room_id: str = Field(..., description="ID de la habitación")
    guest_id: Optional[str] = Field(None, description="ID del huésped principal")
    check_in: datetime = Field(..., description="Fecha/hora de check-in")
    check_out: datetime = Field(..., description="Fecha/hora de check-out")
    status: int = Field(..., description="Estado: 1=Reserva, 2=Check-in, 3=Check-out")
    adults: int = Field(default=1, ge=0)
    children: int = Field(default=0, ge=0)
    babies: int = Field(default=0, ge=0)
    total_price: Optional[Decimal] = None
    currency: str = Field(default="USD")
    source: Optional[str] = None
    notes: Optional[str] = None


class ReservationDetail(ReservationBase):
    """Detalle completo de reserva con relaciones."""
    model_config = ConfigDict(from_attributes=True)

    guest: Optional[GuestResponse] = None
    room: Optional[RoomResponse] = None
    services: list["ServiceResponse"] = []
    payments: list["PaymentResponse"] = []
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime


class ReservationListResponse(BaseModel):
    """Respuesta paginada de reservas."""
    items: list[ReservationDetail]
    total: int
    page: int
    page_size: int
    total_pages: int


class ServiceBase(BaseModel):
    """Base para servicio/consumo."""
    id: Optional[str] = None
    reservation_id: str
    date: datetime
    title: str
    description: Optional[str] = None
    quantity: Decimal = Field(default=Decimal("1"))
    price: Decimal
    total: Decimal


class ServiceResponse(ServiceBase):
    """Respuesta de servicio."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class PaymentBase(BaseModel):
    """Base para pago."""
    id: Optional[str] = None
    reservation_id: str
    date: datetime
    amount: Decimal
    method: Optional[str] = None
    reference: Optional[str] = None
    status: Optional[str] = None


class PaymentResponse(PaymentBase):
    """Respuesta de pago."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class SyncStatus(BaseModel):
    """Estado de sincronización."""
    hotel_id: str
    last_calendar_sync: Optional[datetime] = None
    last_categories_sync: Optional[datetime] = None
    last_full_sync: Optional[datetime] = None
    pending_reservations: int = 0
    errors_last_sync: list[str] = []


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, bool] = {}


class MetricsResponse(BaseModel):
    """Métricas básicas."""
    reservations_total: int
    reservations_today: int
    guests_total: int
    hotels_active: int
    last_sync_duration_ms: Optional[float] = None
    errors_last_hour: int = 0


# Forward references
CategoryResponse.model_rebuild()
RoomResponse.model_rebuild()
ReservationDetail.model_rebuild()
ServiceResponse.model_rebuild()
PaymentResponse.model_rebuild()