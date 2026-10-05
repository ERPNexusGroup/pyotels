"""
API Schemas - Request/Response models for FastAPI endpoints.
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# BASE SCHEMAS
# ============================================================
class HotelBase(BaseModel):
    id: str = Field(..., description="Hotel ID in OtelMS")
    name: str | None = None
    domain: str = "otelms.com"
    is_active: bool = True


class HotelCreate(HotelBase):
    username: str
    password: str


class HotelResponse(HotelBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    updated_at: datetime
    last_sync_at: datetime | None = None


class CategoryBase(BaseModel):
    id: str
    name: str


class CategoryResponse(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    rooms: list["RoomResponse"] = []


class RoomBase(BaseModel):
    id: str
    name: str
    category_id: str


class RoomResponse(RoomBase):
    model_config = ConfigDict(from_attributes=True)

    category: CategoryResponse | None = None
    floor: str | None = None
    max_occupancy: int | None = None
    is_active: bool = True


class GuestBase(BaseModel):
    id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    email: str | None = None
    phone: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    nationality: str | None = None
    country: str | None = None
    city: str | None = None


class GuestResponse(GuestBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    created_at: datetime
    updated_at: datetime


class ServiceBase(BaseModel):
    id: str | None = None
    reservation_id: str
    date: datetime
    title: str
    description: str | None = None
    quantity: Decimal = Decimal("1")
    price: Decimal
    total: Decimal


class ServiceResponse(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class PaymentBase(BaseModel):
    id: str | None = None
    reservation_id: str
    date: datetime
    amount: Decimal
    method: str | None = None
    reference: str | None = None
    status: str | None = None


class PaymentResponse(PaymentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class ReservationBase(BaseModel):
    id: str
    hotel_id: str
    room_id: str
    guest_id: str | None = None
    check_in: datetime
    check_out: datetime
    status: int = Field(..., description="1=Reserva, 2=Check-in, 3=Check-out")
    adults: int = 1
    children: int = 0
    babies: int = 0
    total_price: Decimal | None = None
    currency: str = "USD"
    source: str | None = None
    notes: str | None = None


class ReservationResponse(ReservationBase):
    model_config = ConfigDict(from_attributes=True)

    guest: GuestResponse | None = None
    room: RoomResponse | None = None
    services: list[ServiceResponse] = []
    payments: list[PaymentResponse] = []
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime


class ReservationListResponse(BaseModel):
    items: list[ReservationResponse]
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
    status: int | None = None
    check_in_from: datetime | None = None
    check_in_to: datetime | None = None
    check_out_from: datetime | None = None
    check_out_to: datetime | None = None
    room_id: str | None = None
    guest_id: str | None = None


class SyncStatusResponse(BaseModel):
    hotel_id: str
    last_calendar_sync: datetime | None = None
    last_categories_sync: datetime | None = None
    last_full_sync: datetime | None = None
    pending_reservations: int = 0
    errors_last_sync: list[str] = []


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
    last_sync_duration_ms: float | None = None
    errors_last_hour: int = 0


class SyncResultResponse(BaseModel):
    operation: str
    hotel_id: str
    success: bool
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    errors: list[str] = []
    duration_ms: int = 0


# ============================================================
# ROOM AVAILABILITY (disponibles / ocupadas / checkouts)
# ============================================================
class CategoryAvailability(BaseModel):
    category_id: str
    category_name: str
    total: int
    available: int
    occupied: int


class AvailableRoomsResponse(BaseModel):
    hotel_id: str
    check_in: date
    check_out: date
    total_rooms: int
    available_count: int
    occupied_count: int
    occupancy_rate: float = Field(..., description="Porcentaje 0-100 de ocupación")
    by_category: list[CategoryAvailability] = []
    items: list[RoomResponse] = []


class OccupiedRoomItem(BaseModel):
    reservation_id: str
    room: RoomResponse
    guest_name: str | None = None
    check_in: datetime
    check_out: datetime
    adults: int = 1
    children: int = 0
    nights_remaining: int = Field(0, description="Noches restantes desde la fecha consultada")


class OccupiedRoomsResponse(BaseModel):
    hotel_id: str
    date: date
    occupied_count: int
    items: list[OccupiedRoomItem] = []


class CheckoutItem(BaseModel):
    reservation_id: str
    room: RoomResponse
    guest_name: str | None = None
    check_in: datetime
    check_out: datetime
    adults: int = 1
    children: int = 0
    total_price: Decimal | None = None


class CheckoutsResponse(BaseModel):
    hotel_id: str
    date: date
    count: int
    items: list[CheckoutItem] = []


# ============================================================
# DISPONIBILIDAD POR CATEGORÍA (lo que publica OtelMS)
# ============================================================
class CategoryAvailabilityRow(BaseModel):
    """Una celda del calendario: disponibilidad de una categoría en un día.

    `available` es el número que da OtelMS, no `total - ocupadas`: el hotel
    retiene habitaciones por encima de las ocupadas y marca 0 en días
    bloqueados, así que recalcularlo da cifras equivocadas.
    """

    category_id: str
    category_name: str | None = None
    date: date
    total_rooms: int | None = Field(
        None, description="Habitaciones de la categoría, según el último sync"
    )
    available: int


class CategoryAvailabilityResponse(BaseModel):
    hotel_id: str
    date_from: date
    date_to: date
    count: int
    items: list[CategoryAvailabilityRow] = []


# Forward references
CategoryResponse.model_rebuild()
RoomResponse.model_rebuild()
ReservationResponse.model_rebuild()
