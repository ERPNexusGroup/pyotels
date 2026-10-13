# Plan: Cambiar lógica a disponibilidad OTELMS (calendar_sum)

## Objetivo
Modificar `/rooms/available/enhanced` para usar la disponibilidad que **OtelMS publica en su calendario** (`CategoryAvailability.available` = `calendar_sum`), no la calculada por reservas.

## Flujo de datos actual vs nuevo

| Paso | Actual (calculado) | Nuevo (OTELMS) |
|------|-------------------|----------------|
| 1. Disponibilidad | `RoomRepository.get_available_for_dates()` (excluye reservas overlapping) | `CategoryAvailabilityRepository.get_range()` (lee `available` del calendario) |
| 2. Qué habitaciones | Las que NO tienen reserva | Primeras N habitaciones de la categoría (ordenadas por room_name) |
| 3. Exclusiones | Solo reservas | RoomAvailability manual (is_blocked) + Housekeeping status |
| 4. Tarifas | Por categoría/fecha | Igual (ChannelRateRepository) |

## Algoritmo para "distribuir" disponibilidad OTELMS a habitaciones específicas

Para cada **fecha** en el rango:
1. `cat_avail = CategoryAvailabilityRepository.get_range(hotel_id, date, date)` → lista de `(category_id, available)`
2. `rooms = RoomRepository.get_by_category(category_id)` → todas las habitaciones activas de la categoría
3. `blocked = RoomAvailability WHERE hotel_id AND (room_id IN rooms OR room_id IS NULL) AND date BETWEEN start_date AND end_date AND is_blocked=true` → room_ids bloqueados manualmente
4. `cleaned = HousekeepingStatusRepository.get_cleaned_room_ids_for_date(hotel_id, date)` → room_ids limpios
5. **Candidatos** = `rooms` - `blocked` - (si `only_cleaned` then `rooms` - `cleaned`)
6. **Ordenar** candidatos por `room_name` (determinístico)
7. **Tomar primeros N** = `available` de OtelMS
8. Para esas habitaciones, obtener `ChannelRateRepository.get_for_availability(hotel_id, category_id, date, date)` filtrado por canal

## Endpoint: `GET /rooms/available-for-sale` (nueva ruta, no rompe la existente)

### Query params
- `hotel_id` (required)
- `date_from` (default: today)
- `date_to` (default: date_from + 45)
- `channel` (default: "direct")
- `only_cleaned` (bool, default: true)
- `category_id` (optional)

### Response schema (nuevo o extiende `AvailableRoomsEnhancedResponse`)
```python
class RoomForSaleItem(BaseModel):
    room_id: str
    room_name: str
    category_id: str
    category_name: str
    rate: ChannelRateResponse | None
    status: str  # "cleaned" | "dirty" | "pending"
    blocked_reason: str | None  # si estaba en RoomAvailability

class AvailableForSaleByDate(BaseModel):
    date: date
    category_id: str
    category_name: str
    otelms_available: int  # lo que publica OtelMS
    rooms: list[RoomForSaleItem]

class RoomsAvailableForSaleResponse(BaseModel):
    hotel_id: str
    date_from: date
    date_to: date
    channel: str
    only_cleaned: bool
    items: list[AvailableForSaleByDate]
```

## Archivos a modificar

1. **`src/otelms/api/schemas.py`** — Add `RoomForSaleItem`, `AvailableForSaleByDate`, `RoomsAvailableForSaleResponse`
2. **`src/otelms/domain/repositories/__init__.py`** — Add `RoomAvailabilityRepository` (new file or inline) with `get_blocked_room_ids_for_date(hotel_id, date, room_ids)`
3. **`src/otelms/api/routes/rooms.py`** — Add `GET /rooms/available-for-sale` endpoint
   - Deps: `get_category_availability_repo`, `get_room_repo`, `get_channel_rate_repo`, `get_housekeeping_status_repo`, `get_room_availability_repo` (new)
4. **`src/otelms/api/dependencies.py`** — Add `get_room_availability_repo()`

## Sin migración BD
Todas las tablas ya existen: `category_availability`, `rooms`, `room_availability`, `channel_rates`, `housekeeping_status`.

## Próximo paso
Aprobar plan → implementar.