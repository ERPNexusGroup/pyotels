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
    legal_name: str | None = None
    phone: str | None = None
    email: str | None = None
    web_address: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    post_code: str | None = None
    gps_coordinates: str | None = None
    star_rating: int | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    timezone: str | None = None
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


class DealerBase(BaseModel):
    id: str
    hotel_id: str
    name: str
    phone: str | None = None
    address: str | None = None
    is_active: bool = True


class DealerResponse(DealerBase):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaymentMethodBase(BaseModel):
    id: str
    hotel_id: str
    name: str
    type: str | None = None
    is_active: bool = True


class PaymentMethodResponse(PaymentMethodBase):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PropertyServiceBase(BaseModel):
    id: str
    hotel_id: str
    name: str
    label: str | None = None
    is_active: bool = True


class PropertyServiceResponse(PropertyServiceBase):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    updated_at: datetime | None = None


class FrontDeskStatusResponse(BaseModel):
    hotel_id: str
    status_date: str
    departures_today: int = 0
    arrivals_today: int = 0
    inhouse_today: int = 0
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class PriceCalendarCellResponse(BaseModel):
    date: str
    room_id: str
    dealer_id: str
    category_id: str
    price: float | None = None


class ReservationNightRateBase(BaseModel):
    id: str | None = None
    reservation_id: str
    date: date
    rate_name: str | None = None
    price: Decimal


class ReservationNightRateResponse(ReservationNightRateBase):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime | None = None


class ReservationChangeHistoryBase(BaseModel):
    id: str | None = None
    reservation_id: str
    date: datetime | str | None = None
    user: str | None = None
    event_type: str | None = None
    action: str | None = None
    amount: Decimal | str | None = None
    description: str | None = None


class ReservationChangeHistoryResponse(ReservationChangeHistoryBase):
    model_config = ConfigDict(from_attributes=True)


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
    vehicle_brand: str | None = None
    vehicle_color: str | None = None
    vehicle_plate: str | None = None
    nights: int | None = None
    rate_name: str | None = None
    channel_reservation_id: str | None = None
    room_reservation_id: str | None = None


class ReservationResponse(ReservationBase):
    model_config = ConfigDict(from_attributes=True)

    guest: GuestResponse | None = None
    room: RoomResponse | None = None
    services: list[ServiceResponse] = []
    payments: list[PaymentResponse] = []
    night_rates: list[ReservationNightRateResponse] = []
    history: list[ReservationChangeHistoryResponse] = []
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


# ============================================================
# ROOM AVAILABILITY ENHANCED (con tarifas y housekeeping)
# ============================================================
class ChannelRatePerDate(BaseModel):
    """Tarifa de un canal para una fecha específica."""
    channel: str = Field(..., description="Canal de venta: direct, ota, booking, expedia...")
    rate_id: str = Field(..., description="1 = Standard, 2 = Feriados")
    price: Decimal
    currency: str = "USD"
    min_stay: int | None = None


class RoomRatePerDate(BaseModel):
    """Tarifas de una habitación (por categoría) para una fecha."""
    date: date
    rates: list[ChannelRatePerDate] = []


class RoomHousekeepingPerDate(BaseModel):
    """Estado de housekeeping de una habitación para una fecha."""
    date: date
    status: int = Field(..., description="0=pending, 1=in_progress, 2=cleaned")
    status_label: str = Field(..., description="Etiqueta del estado")


class AvailableRoomEnhanced(RoomResponse):
    """Habitación disponible con tarifas y housekeeping por fecha."""
    rates_per_date: list[RoomRatePerDate] = Field(
        default_factory=list,
        description="Tarifas por canal para cada fecha del rango"
    )
    housekeeping_per_date: list[RoomHousekeepingPerDate] = Field(
        default_factory=list,
        description="Estado de limpieza para cada fecha del rango"
    )


class AvailableRoomsEnhancedResponse(BaseModel):
    """Respuesta extendida con tarifas y housekeeping por habitación/fecha."""
    hotel_id: str
    check_in: date
    check_out: date
    total_rooms: int
    available_count: int
    occupied_count: int
    occupancy_rate: float
    by_category: list[CategoryAvailability] = []
    items: list[AvailableRoomEnhanced] = []
    date_range: list[date] = Field(default_factory=list, description="Fechas en el rango (check_in a check_out - 1)")


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
# RESTRICCIONES (celdas cerradas)
# ============================================================
class RestrictionRow(BaseModel):
    """Una celda cerrada de la rejilla de restricciones.

    La restricción la define la terna (categoría, tarifa, día): es lo que el
    portal cierra. `closed` sale de las clases del `<td>`, que es la única
    forma de leerlo: el portal no lo serializa en ningún atributo.
    """

    category_id: str
    category_name: str | None = None
    rate_id: str = Field("1", description="1 = Standard, 2 = Feriados")
    date: date
    closed: bool = True


class RestrictionResponse(BaseModel):
    hotel_id: str
    date_from: date
    date_to: date
    source: str = Field(
        "otelms/restrict_calendar",
        description="Siempre en vivo: no hay tabla de restricciones, se lee del portal",
    )
    count: int
    items: list[RestrictionRow] = []


# ============================================================
# CHANNEL RATES (Issue 2)
# ============================================================
class ChannelRateBase(BaseModel):
    category_id: str
    rate_id: str = Field("1", description="1 = Standard, 2 = Feriados")
    channel: str = Field(..., description="Canal de venta: direct, ota, booking, expedia...")
    date: date
    price: Decimal
    currency: str = "USD"
    min_stay: int | None = None


class ChannelRateResponse(ChannelRateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hotel_id: str
    created_at: datetime


# ============================================================
# ROOMS AVAILABLE FOR SALE (habitaciones a la venta con tarifa OTELMS)
# ============================================================
class RoomForSaleItem(BaseModel):
    """Habitación disponible para vender con su tarifa programada."""
    room_id: str
    room_name: str
    category_id: str
    category_name: str
    rate: ChannelRateResponse | None = None
    status: str = Field(..., description="Estado housekeeping: cleaned, dirty, pending")
    blocked_reason: str | None = None


class AvailableForSaleByDate(BaseModel):
    """Disponibilidad por fecha para una categoría."""
    date: date
    category_id: str
    category_name: str
    otelms_available: int = Field(..., description="Habitaciones disponibles según OtelMS (calendar_sum)")
    rooms: list[RoomForSaleItem] = []


class RoomsAvailableForSaleResponse(BaseModel):
    """Habitaciones disponibles para vender con tarifa (basado en disponibilidad OTELMS)."""
    hotel_id: str
    date_from: date
    date_to: date
    channel: str
    only_cleaned: bool
    items: list[AvailableForSaleByDate] = []


# ============================================================
# IN-HOUSE (huéspedes dentro del hotel)
# ============================================================
class InHouseItem(BaseModel):
    """Un huésped que pernocta la fecha consultada.

    `status` es el estado que trae OtelMS, no el criterio de selección: el
    portal deja reservas en "Check in" con salida ya pasada, así que el in-house
    se decide por `check_in <= fecha < check_out`.
    """

    reservation_id: str
    guest_name: str | None = None
    room: RoomResponse
    check_in: datetime
    check_out: datetime
    nights: int = Field(..., description="Noches de la estancia")
    nights_elapsed: int = Field(..., description="Noches ya cumplidas hasta la fecha")
    nights_remaining: int
    adults: int = 1
    children: int = 0
    total_price: Decimal | None = None
    status: int | None = Field(None, description="Estado en OtelMS: 1 Reservación, 2 Check in, 3 Check out")
    source: str | None = None


class InHouseResponse(BaseModel):
    hotel_id: str
    date: date
    in_house_count: int
    occupied_rooms: int = Field(
        0, description="Habitaciones distintas ocupadas (una habitación, varios huéspedes)"
    )
    items: list[InHouseItem] = []


# ============================================================
# HOUSEKEEPING (limpieza de habitaciones)
# ============================================================
class HousekeepingItem(BaseModel):
    """Una habitación que necesita limpieza en la fecha consultada.

    `cleaning_type` indica el tipo de limpieza requerida:
    - "full" (limpieza completa): habitación con check-out hoy (huésped se fue)
    - "stay_over" (limpieza continua): habitación ocupada que continúa la reserva
    - "blocked" (bloqueada): habitación sin reserva activa para la fecha
    - "income_generating" (ingresos): habitación con reserva futura que generará ingresos
    """
    model_config = ConfigDict(from_attributes=True)

    room_id: str
    room_name: str
    category_id: str | None = None
    category_name: str | None = None
    reservation_id: str
    guest_name: str | None = None
    check_in: datetime
    check_out: datetime
    adults: int = 1
    children: int = 0
    nights_remaining: int = Field(..., description="Noches restantes desde la fecha consultada")
    cleaning_type: str = Field(..., description="full=limpieza completa (checkout), stay_over=limpieza continua (pernocta), blocked=bloqueada, income=ingresos")
    status: int = Field(..., description="Estado en OtelMS: 1 Reservación, 2 Check in, 3 Check out")


class HousekeepingResponse(BaseModel):
    hotel_id: str
    date: date
    full_cleaning: list[HousekeepingItem] = Field(..., description="Habitaciones con checkout hoy (limpieza completa)")
    continuous_cleaning: list[HousekeepingItem] = Field(..., description="Habitaciones que pernoctan (limpieza continua)")
    blocked_rooms: list[HousekeepingItem] = Field(..., description="Habitaciones bloqueadas (sin reserva activa)")
    income_generating_rooms: list[HousekeepingItem] = Field(..., description="Habitaciones con reserva futura (generarán ingresos)")
    total_rooms_to_clean: int = Field(..., description="Suma de full_cleaning + continuous_cleaning")


# ============================================================
# HOUSEKEEPING STATUS UPDATE (Issue 3)
# ============================================================

class HousekeepingStatusUpdate(BaseModel):
    """Solicitud para actualizar el estado de limpieza de una habitación."""
    status: int = Field(..., description="0=pending, 1=in_progress, 2=cleaned")
    updated_by: str | None = Field(None, max_length=255, description="Quién realiza el cambio")


class HousekeepingStatusResponse(BaseModel):
    """Respuesta al cambiar el estado de limpieza."""
    model_config = ConfigDict(from_attributes=True)

    room_id: str
    room_name: str | None = None
    date: date
    status: int
    status_label: str
    updated_by: str | None = None
    updated_at: datetime


class HousekeepingResetResponse(BaseModel):
    """Respuesta al reiniciar estados de limpieza de una fecha."""
    date: date
    reset_count: int
    message: str


# ============================================================
# PENDING CHARGES (Issue 1)
# ============================================================
class PendingChargesItem(BaseModel):
    """Una reserva con saldos pendientes.

    `pending` = total de servicios (room_charges + room_price + folio)
    menos total pagado. Puede ser negativo si el huésped pagó de más.
    """
    model_config = ConfigDict(from_attributes=True)

    reservation_id: str
    guest_name: str | None = None
    room_id: str | None = None
    room_name: str | None = None
    check_in: datetime
    check_out: datetime
    nights: int = Field(..., description="Noches de la estancia")
    total_charges: Decimal = Field(..., description="Suma de todos los servicios (room + cargos)")
    total_paid: Decimal = Field(..., description="Suma de todos los pagos")
    pending: Decimal = Field(..., description="Saldo pendiente = total_charges - total_paid")
    currency: str = "USD"
    status: int | None = None


class PendingChargesResponse(BaseModel):
    """Lista de reservas con saldos pendientes."""
    hotel_id: str
    count: int = Field(..., description="Reservas con pending != 0")
    total_pending: Decimal = Field(..., description="Suma de todos los pendientes")
    items: list[PendingChargesItem] = []


# Forward references
CategoryResponse.model_rebuild()
RoomResponse.model_rebuild()
ReservationResponse.model_rebuild()
