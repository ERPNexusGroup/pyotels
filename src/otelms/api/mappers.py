"""
Mapeo explícito entidad ORM -> esquema de respuesta.

Los esquemas anidados (`CategoryResponse.rooms` <-> `RoomResponse.category`) son
mutuamente recursivos, así que serializarlos con `from_attributes=True`
directamente sobre entidades ORM no funciona por dos motivos:

1. La relación se resuelve en diferido cuando no viene precargada, y fuera del
   contexto async eso lanza `MissingGreenlet`.
2. Aunque venga precargada, cat -> rooms -> room.category -> rooms -> ... es un
   ciclo y Pydantic aborta con `recursion_loop - cyclic reference detected`.

Los mappers de aquí cortan el ciclo constructing esquemas planos a partir de
columnas ya cargadas: la categoría anidada dentro de una habitación se devuelve
como stub `{id, name}` con `rooms=[]`, que es toda la información útil y no
reintroduce el ciclo.

Para leer una relación sin disparar SQL se usa `obj.__dict__.get(nombre)`: solo
devuelve algo si la relación ya está precargada, y `None` si no lo está.
"""
from decimal import Decimal
from typing import Any, Literal

from otelms.api.schemas import (
    CategoryResponse,
    DealerResponse,
    GuestResponse,
    PaymentMethodResponse,
    PaymentResponse,
    PropertyServiceResponse,
    ReservationChangeHistoryResponse,
    ReservationNightRateResponse,
    ReservationResponse,
    RoomResponse,
    ServiceResponse,
    format_money,
)
from otelms.domain.entities import (
    Category,
    Dealer,
    Guest,
    Payment,
    PaymentMethod,
    PropertyService,
    Reservation,
    ReservationChangeHistory,
    ReservationNightRate,
    Room,
    Service,
)

# Sentinel para habitación sin categoría (category_id NULL en BD, posible en
# datos del sync). Mantiene el contrato `RoomResponse.category_id: str`.
UNCATEGORIZED = "uncategorized"


def _loaded(obj: object, name: str) -> Any:
    """Devuelve la relación `name` solo si ya está precargada; None si no."""
    return obj.__dict__.get(name)


def room_response(room: Room) -> RoomResponse:
    """RoomResponse desde columnas ya cargadas.

    La categoría se incluye como stub {id, name} si viene precargada; si no,
    `category` queda None. Nunca se accede a `room.category.rooms`.
    """
    category = None
    loaded_cat = _loaded(room, "category")
    if loaded_cat is not None:
        category = CategoryResponse(id=loaded_cat.id, name=loaded_cat.name or loaded_cat.id)

    return RoomResponse(
        id=room.id,
        name=room.name,
        category_id=room.category_id or UNCATEGORIZED,
        category=category,
        floor=room.floor,
        max_occupancy=room.max_occupancy,
        is_active=room.is_active,
    )


def category_response(category: Category) -> CategoryResponse:
    """CategoryResponse con sus habitaciones.

    Las habitaciones se mapearn con room_response, que no reintroduce la
    relación category->rooms, así que no hay ciclo.
    """
    rooms = _loaded(category, "rooms") or []
    return CategoryResponse(
        id=category.id,
        name=category.name,
        rooms=[room_response(r) for r in rooms],
    )


def guest_response(guest: Guest) -> GuestResponse:
    return GuestResponse(
        id=guest.id,
        first_name=guest.first_name,
        last_name=guest.last_name,
        middle_name=guest.middle_name,
        email=guest.email,
        phone=guest.phone,
        document_type=guest.document_type,
        document_number=guest.document_number,
        address=guest.address,
        nationality=guest.nationality,
        country=guest.country,
        city=guest.city,
        full_name=guest.full_name,
        created_at=guest.created_at,
        updated_at=guest.updated_at,
    )


def service_response(service: Service) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
        reservation_id=service.reservation_id,
        date=service.date,
        title=service.title,
        description=service.description,
        quantity=service.quantity,
        price=service.price,
        total=service.total,
        created_at=service.created_at,
    )


def payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        reservation_id=payment.reservation_id,
        date=payment.date,
        amount=payment.amount,
        method=payment.method,
        reference=payment.reference,
        status=payment.status,
        created_at=payment.created_at,
    )


def dealer_response(dealer: Dealer) -> DealerResponse:
    return DealerResponse(
        id=dealer.id,
        hotel_id=dealer.hotel_id,
        name=dealer.name,
        phone=dealer.phone,
        address=dealer.address,
        is_active=dealer.is_active,
        created_at=dealer.created_at,
        updated_at=dealer.updated_at,
    )


def payment_method_response(pm: PaymentMethod) -> PaymentMethodResponse:
    return PaymentMethodResponse(
        id=pm.id,
        hotel_id=pm.hotel_id,
        name=pm.name,
        type=pm.type,
        is_active=pm.is_active,
        created_at=pm.created_at,
        updated_at=pm.updated_at,
    )


def property_service_response(svc: PropertyService) -> PropertyServiceResponse:
    return PropertyServiceResponse(
        id=svc.id,
        hotel_id=svc.hotel_id,
        name=svc.name,
        label=svc.label,
        is_active=svc.is_active,
        created_at=svc.created_at,
        updated_at=svc.updated_at,
    )


def night_rate_response(rate: ReservationNightRate) -> ReservationNightRateResponse:
    return ReservationNightRateResponse(
        id=rate.id,
        reservation_id=rate.reservation_id,
        date=rate.date,
        rate_name=rate.rate_name,
        price=rate.price,
        created_at=rate.created_at,
    )


def change_history_response(item: ReservationChangeHistory) -> ReservationChangeHistoryResponse:
    return ReservationChangeHistoryResponse(
        id=item.id,
        reservation_id=item.reservation_id,
        date=item.date,
        user=item.user,
        event_type=item.event_type,
        action=item.action,
        amount=item.amount,
        description=item.description,
    )


def compute_billing_summary(
    reservation: Reservation,
    money_unit: Literal["decimal", "cents"] = "decimal",
) -> dict[str, Any]:
    """Calcula totales consolidados y guarda de saldo sin aritmética flotante."""
    services = _loaded(reservation, "services") or []
    payments = _loaded(reservation, "payments") or []
    night_rates = _loaded(reservation, "night_rates") or []

    accom_services = [
        s for s in services
        if "alojamiento" in (s.title or "").lower() and "-night-" not in str(s.id)
    ]
    if accom_services:
        accommodation_dec = sum((Decimal(str(s.total)) for s in accom_services), Decimal("0.00"))
    else:
        accommodation_dec = sum((Decimal(str(r.price)) for r in night_rates), Decimal("0.00"))

    other_services = [
        s for s in services
        if "alojamiento" not in (s.title or "").lower() and "-night-" not in str(s.id)
    ]
    services_dec = sum((Decimal(str(s.total)) for s in other_services), Decimal("0.00"))
    payments_dec = sum((Decimal(str(p.amount)) for p in payments), Decimal("0.00"))
    computed_dec = accommodation_dec + services_dec - payments_dec

    otelms_bal_dec = (
        Decimal(str(reservation.otelms_balance))
        if getattr(reservation, "otelms_balance", None) is not None
        else None
    )
    deep_synced = getattr(reservation, "deep_synced_at", None) is not None
    mismatch = (
        otelms_bal_dec is None
        or not deep_synced
        or otelms_bal_dec.quantize(Decimal("0.01")) != computed_dec.quantize(Decimal("0.01"))
    )
    is_billable = computed_dec.quantize(Decimal("0.01")) == Decimal("0.00") and not mismatch

    return {
        "money_unit": money_unit,
        "accommodation_total": format_money(accommodation_dec, money_unit),
        "services_total": format_money(services_dec, money_unit),
        "payments_total": format_money(payments_dec, money_unit),
        "otelms_balance": format_money(otelms_bal_dec, money_unit),
        "computed_balance": format_money(computed_dec, money_unit),
        "balance_mismatch": mismatch,
        "is_billable": is_billable,
    }


def reservation_response(
    reservation: Reservation,
    money_unit: Literal["decimal", "cents"] = "decimal",
) -> ReservationResponse:
    """ReservationResponse con las relaciones que ya vinieron precargadas."""
    guest = _loaded(reservation, "guest")
    room = _loaded(reservation, "room")
    night_rates = _loaded(reservation, "night_rates") or []
    history = _loaded(reservation, "change_history") or []
    billing = compute_billing_summary(reservation, money_unit=money_unit)

    return ReservationResponse(
        id=reservation.id,
        hotel_id=reservation.hotel_id,
        room_id=reservation.room_id,
        guest_id=reservation.guest_id,
        check_in=reservation.check_in,
        check_out=reservation.check_out,
        status=reservation.status,
        adults=reservation.adults,
        children=reservation.children,
        babies=reservation.babies,
        total_price=reservation.total_price,
        currency=reservation.currency,
        source=reservation.source,
        notes=reservation.notes,
        vehicle_brand=reservation.vehicle_brand,
        vehicle_color=reservation.vehicle_color,
        vehicle_plate=reservation.vehicle_plate,
        nights=reservation.nights,
        rate_name=reservation.rate_name,
        channel_reservation_id=reservation.channel_reservation_id,
        room_reservation_id=reservation.room_reservation_id,
        guest=guest_response(guest) if guest is not None else None,
        room=room_response(room) if room is not None else None,
        services=[service_response(s) for s in (_loaded(reservation, "services") or [])],
        payments=[payment_response(p) for p in (_loaded(reservation, "payments") or [])],
        night_rates=[night_rate_response(r) for r in night_rates],
        history=[change_history_response(h) for h in history],
        **billing,
        created_at=reservation.created_at,
        updated_at=reservation.updated_at,
        last_synced_at=reservation.last_synced_at,
    )


def guest_name(reservation: Reservation) -> str | None:
    """Nombre completo del huésped de una reserva, o None si no hay guest."""
    guest = _loaded(reservation, "guest")
    if guest is None:
        return None
    return guest.full_name or None
