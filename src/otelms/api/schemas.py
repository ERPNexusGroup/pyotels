"""
API Schemas - Request/Response models for FastAPI endpoints.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# BASE SCHEMAS
# ============================================================
class HotelBase(BaseModel):
    id: str = Field(..., description="Hotel ID in OtelMS")
    name: Optional[str] = None
    domain: str = "otelms.com"
    is_active: bool = True


class HotelCreate(HotelBase):
    username: str
    password: str


class HotelResponse(HotelBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    updated_at: datetime
    last_sync_at: Optional[datetime] = None


class CategoryBase(BaseModel):
    id: str
    name: str


class CategoryResponse(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    rooms: List["RoomResponse"] = []


class RoomBase(BaseModel):
    id: str
    name: str
    category_id: str


class RoomResponse(RoomBase):
    model_config = ConfigDict(from_attributes=True)

    category: Optional[CategoryResponse] = None
    floor: Optional[str] = None
    max_occupancy: Optional[int] = None
    is_active: bool = True


class GuestBase(BaseModel):
    id: Optional[str] = None
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
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    created_at: datetime
    updated_at: datetime


class ServiceBase(BaseModel):
    id: Optional[str] = None
    reservation_id: str
    date: datetime
    title: str
    description: Optional[str] = None
    quantity: Decimal = Decimal("1")
    price: Decimal
    total: Decimal


class ServiceResponse(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class PaymentBase(BaseModel):
    id: Optional[str] = None
    reservation_id: str
    date: datetime
    amount: Decimal
    method: Optional[str] = None
    reference: Optional[str] = None
    status: Optional[str] = None


class PaymentResponse(PaymentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class ReservationBase(BaseModel):
    id: str
    hotel_id: str
    room_id: str
    guest_id: Optional[str] = None
    check_in: datetime
    check_out: datetime
    status: int = Field(..., description="1=Reserva, 2=Check-in, 3=Check-out")
    adults: int = 1
    children: int = 0
    babies: int = 0
    total_price: Optional[Decimal] = None
    currency: str = "USD"
    source: Optional[str] = None
    notes: Optional[str] = None


class ReservationResponse(ReservationBase):
    model_config = ConfigDict(from_attributes=True)

    guest: Optional[GuestResponse] = None
    room: Optional[RoomResponse] = None
    services: List[ServiceResponse] = []
    payments: List[PaymentResponse] = []
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime


class ReservationListResponse(BaseModel):
    items: List[ReservationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================
# QUERY PARAMETERS
# ============================================================
class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)


class ReservationFilterParams(BaseModel):
    status: Optional[int] = None
    check_in_from: Optional[datetime] = None
    check_in_to: Optional[datetime] = None
    check_out_from: Optional[datetime] = None
    check_out_to: Optional[datetime] = None
    room_id: Optional[str] = None
    guest_id: Optional[str] = None


class SyncStatusResponse(BaseModel):
    hotel_id: str
    last_calendar_sync: Optional[datetime] = None
    last_categories_sync: Optional[datetime] = None
    last_full_sync: Optional[datetime] = None
    pending_reservations: int = 0
    errors_last_sync: List[str] = []


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, bool] = {}


class MetricsResponse(BaseModel):
    reservations_total: int
    reservations_today: int
    guests_total: int
    hotels_active: int
    last_sync_duration_ms: Optional[float] = None
    errors_last_hour: int = 0


class SyncResultResponse(BaseModel):
    operation: str
    hotel_id: str
    success: bool
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    errors: List[str] = []
    duration_ms: int = 0


# Forward references
CategoryResponse.model_rebuild()
RoomResponse.model_rebuild()
ReservationResponse.model_rebuild()