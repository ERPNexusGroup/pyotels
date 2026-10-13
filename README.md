# OtelMS API - Unofficial API for OtelMS

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-green)](https://fastapi.tiangolo.com)
[![Camoufox](https://img.shields.io/badge/Camoufox-0.5%2B-orange)](https://github.com/daijro/camoufox)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red)](https://sqlalchemy.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> **⚠️ Disclaimer**: This is an unofficial API for OtelMS. Use responsibly and only with explicit authorization from the hotel/property owner. Scraping may violate terms of service. The authors are not responsible for any misuse.

---

## 🎯 Overview

OtelMS API provides a robust, production-ready solution for extracting hotel reservation data from the OtelMS platform and exposing it via a clean REST API. Built with modern Python async architecture, it handles anti-bot protection, rate limiting, and data persistence automatically.

### Key Features

- 🕷️ **Anti-detect Scraping** - Camoufox (Firefox-based) with fingerprint randomization
- ⚡ **Async Architecture** - Full async/await with FastAPI, SQLAlchemy 2.x, Playwright
- 🛡️ **Rate Limiting** - Distributed token bucket (Redis) per hotel
- 🔄 **Auto-retry & Recovery** - Tenacity policies, session management, auto-relogin
- 🗄️ **Persistence** - PostgreSQL/SQLite with SQLAlchemy + Alembic migrations
- 📊 **Observability** - Structured logging (structlog), Prometheus metrics, OpenTelemetry tracing
- ⏰ **Background Jobs** - Celery + Redis for scheduled sync (calendar, categories, details)
- 🔐 **API Security** - API Key authentication with rate limiting
- 🐳 **Containerized** - Multi-stage Docker builds, docker-compose for full stack

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FastAPI       │     │   Celery        │     │   Camoufox      │
│   REST API      │────▶│   Workers       │────▶│   Browser Pool  │
│   (Port 8000)   │     │   (Beat +       │     │   (Anti-detect) │
└─────────────────┘     │    Workers)     │     └────────┬────────┘
        │               └────────┬────────┘              │
        │                        │                       ▼
        ▼                        ▼              ┌─────────────────┐
┌─────────────────┐     ┌─────────────────┐     │   OtelMS        │
│   PostgreSQL    │◀───▶│   Redis         │     │   Platform      │
│   (Primary DB)  │     │   (Cache +      │     │   (Target)      │
└─────────────────┘     │    Queue)       │     └─────────────────┘
                        └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (recommended)
- Or: PostgreSQL 16+, Redis 7+, uv package manager

### Option 1: Docker Compose (Recommended)

```bash
# Clone and configure
git clone <repo>
cd scraping_otelms_api
cp .env.example .env
# Edit .env with your credentials

# Start all services
docker compose -f docker/docker-compose.yml up -d

# Verify
curl http://localhost:8000/health
# {"status":"healthy","checks":{"database":true,"cache":true},"version":"1.0.0"}
```

### Option 2: Local Development

```bash
# Install dependencies
uv sync --all-extras

# Setup database
cp .env.example .env
# Edit .env with DATABASE_URL=sqlite+aiosqlite:///./otelms.db (for quick start)

# Initialize DB
otelms db init
otelms db seed

# Run API server
otelms api --reload

# Run worker (in separate terminal)
otelms worker

# Run scheduler (in separate terminal)
otelms beat
```

---

## 📖 API Documentation

Once running, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

### Authentication

All endpoints require API Key in header:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/hotels
```

**Local testing without API Key:** Set `API_KEY_REQUIRED=false` in your `.env` to
bypass API key verification (Swagger UI will work without headers). This is only
for local development — leave `true` (default) in staging and production.

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/health/ready` | GET | Kubernetes readiness |
| `/health/live` | GET | Kubernetes liveness |
| `/metrics` | GET | Prometheus metrics |
| `/hotels` | GET | List hotels |
| `/hotels` | POST | Create hotel |
| `/hotels/{id}` | GET | Get hotel |
| `/hotels/{id}` | PATCH | Update hotel |
| `/reservations` | GET | List reservations (paginated) |
| `/reservations/{id}` | GET | Get reservation with details |
| `/reservations/today/checkins` | GET | Today's check-ins |
| `/reservations/today/checkouts` | GET | Today's check-outs |
| `/reservations/in-house` | GET | Guests staying the night of a given date |
| `/reservations/sync/calendar` | POST | Trigger calendar sync |
| `/reservations/sync/categories` | POST | Trigger categories sync |
| `/reservations/sync/full` | POST | Trigger full sync |
| `/reservations/sync/history` | GET | Sync history |
| `/guests` | GET | List guests (searchable) |
| `/guests/{id}` | GET | Get guest |
| `/guests` | POST | Create guest |
| `/categories` | GET | List categories with rooms |
| `/categories/{id}` | GET | Get category with rooms |
| `/categories/{id}/rooms` | GET | Rooms of a category |
| `/categories/availability` | GET | Availability per category and day, as OtelMS publishes it |
| `/restrictions` | GET | Closed dates per category and rate, read live from the portal |
| `/categories/availability-with-rates` | GET | Availability per category/day with channel rates |
| `/housekeeping` | GET | Housekeeping plan (full, continuous, blocked, income) |
| `/housekeeping/full-cleaning` | GET | Only full cleaning (checkouts today) |
| `/housekeeping/stay-over` | GET | Only continuous cleaning (stay-overs) |
| `/housekeeping/{room_id}` | PATCH | Update housekeeping status for a room/date |
| `/housekeeping/reset` | POST | Reset all housekeeping statuses for a date |
| `/rooms/available/enhanced` | GET | Available rooms with rates & housekeeping per date |
| `/rooms/available-for-sale` | GET | Rooms available for sale with OTELMS rates |

### Category availability

`GET /categories/availability?hotel_id=18330&date_from=2026-10-05&date_to=2026-11-19`
returns one row per category and day, the same number the OtelMS calendar shows:

```json
{"category_id": "13", "category_name": "Matrimonial", "date": "2026-10-05",
 "total_rooms": 12, "available": 8}
```

`available` is **OtelMS's own figure**, not `total - occupied`. The two disagree
on 163 of the 414 cells of a current sync: the hotel holds rooms back above the
occupied ones (a 12-room category never goes above 10) and closes whole days
without any reservation behind them. Recomputing it produces wrong numbers, so
the value is scraped from the calendar's summary row (`div.calendar_sum`) and
stored in `category_availability`. It is filled by the calendar sync, not by the
categories sync — the numbers arrive with the grid. Details in
`docs/otelms_endpoints.md` §2.1.



### Enhanced Room Availability (Tarifas y Housekeeping por habitación/fecha)

`GET /rooms/available/enhanced?hotel_id=18330&check_in=2026-10-07&check_out=2026-10-12` returns available rooms with channel rates and housekeeping status per date:

```json
{
  "hotel_id": "18330",
  "check_in": "2026-10-07",
  "check_out": "2026-10-12",
  "total_rooms": 45,
  "available_count": 18,
  "occupied_count": 27,
  "occupancy_rate": 60.0,
  "by_category": [
    {"category_id": "13", "category_name": "Matrimonial", "total": 20, "available": 8, "occupied": 12}
  ],
  "items": [
    {
      "id": "101",
      "name": "101",
      "category_id": "13",
      "category_name": "Matrimonial",
      "floor": 1,
      "max_occupancy": 2,
      "is_active": true,
      "rates_per_date": [
        {"date": "2026-10-07", "rates": [{"channel": "direct", "rate_id": "1", "price": 120.00, "currency": "USD", "min_stay": 1}]},
        {"date": "2026-10-08", "rates": [{"channel": "direct", "rate_id": "1", "price": 120.00, "currency": "USD", "min_stay": 1}]}
      ],
      "housekeeping_per_date": [
        {"date": "2026-10-07", "status": 0, "status_label": "pending"},
        {"date": "2026-10-08", "status": 2, "status_label": "cleaned"}
      ]
    }
  ],
  "date_range": ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"]
}
```

### Rooms Available for Sale (Habitaciones a la venta con tarifa OTELMS)

`GET /rooms/available-for-sale?hotel_id=18330&date_from=2026-10-07&date_to=2026-10-14&channel=direct` returns rooms available for sale based on **OtelMS calendar availability** (not computed from reservations), with rates and housekeeping:

```json
{
  "hotel_id": "18330",
  "date_from": "2026-10-07",
  "date_to": "2026-10-14",
  "channel": "direct",
  "only_cleaned": false,
  "items": [
    {
      "date": "2026-10-07",
      "category_id": "13",
      "category_name": "Matrimonial",
      "otelms_available": 8,
      "rooms": [
        {
          "room_id": "101",
          "room_name": "101",
          "category_id": "13",
          "category_name": "Matrimonial",
          "rate": {
            "category_id": "13",
            "rate_id": "1",
            "channel": "direct",
            "date": "2026-10-07",
            "price": 120.00,
            "currency": "USD",
            "min_stay": 1,
            "id": "rate-uuid",
            "hotel_id": "18330",
            "created_at": "2026-10-01T00:00:00Z"
          },
          "status": "pending",
          "blocked_reason": null
        }
      ]
    }
  ]
}
```

**Query params:**
- `channel` — canal de venta (default: "direct")
- `only_cleaned` — solo habitaciones con housekeeping status=cleaned (default: false)

### In-house

`GET /reservations/in-house?hotel_id=18330&target_date=2026-10-05` lists who is
sleeping in the hotel on a given night, with the nights elapsed and remaining:

```json
{"reservation_id": "23356", "guest_name": "Bejot Louis",
 "room": {"id": "107", "name": "107", "category_id": "13"},
 "check_in": "2026-09-20T05:00:00Z", "check_out": "2026-10-06T05:00:00Z",
 "nights": 16, "nights_elapsed": 15, "nights_remaining": 1, "status": 1}
```

OtelMS has **no in-house view** — the whole menu was walked and it isn't there
(`docs/otelms_endpoints.md` §4), so the list is derived from reservations. The
obvious source of truth is the wrong one: of the 270 reservations in the portal,
the 22 flagged `Estado == "Check in"` all have a check-out already in the past
and none of them covers the day being asked about. The criterion that actually
holds is the date range, `check_in <= target_date < check_out`, and the count is
of reservations, not of occupied rooms. Guests and room numbers come from
`RoomRepository.get_occupied_for_date`, which already joined them.

### Closed dates (restrictions)

`GET /restrictions?hotel_id=18330&date_from=2026-11-18&date_to=2026-11-19`
returns only the **closed** cells of the OtelMS restriction grid:

```json
{"category_id": "21", "category_name": "Overbooking", "rate_id": "1",
 "date": "2026-11-19", "closed": true}
```

Unlike every other endpoint in the API, this one **scrapes OtelMS on each
call** — there is no `room_restrictions` table. That is deliberate: closures
are few and move fast (reception opens a day and it changes within the hour),
so a stored snapshot would be stale exactly where it matters most. The
`source` field is always `"otelms/restrict_calendar"` so a client can tell a
live reading from a cached one. Only closed cells are returned, so a missing
`{category_id, date}` pair means **open**, not "no data". The grid holds 46
days; asking for more returns fewer cells, not an error.

The write side (closing and opening dates) is `src/otelms/scraping/restrictions.py`
and is not exposed over HTTP yet. Closing a day is three chained calls, not one
PUT — see `docs/otelms_endpoints.md` §4.4.



### Channel Rates (Tarifas por canal)

`GET /categories/availability-with-rates?hotel_id=18330&date_from=2026-10-07&date_to=2026-10-14` returns availability per category/day with channel rates:

```json
{
  "hotel_id": "18330",
  "date_from": "2026-10-07",
  "date_to": "2026-10-14",
  "count": 14,
  "items": [
    {
      "category_id": "13",
      "category_name": "Matrimonial",
      "date": "2026-10-07",
      "available": 8,
      "total_rooms": 12,
      "rates": [
        {
          "channel": "direct",
          "rate_id": "1",
          "price": 120.00,
          "currency": "USD",
          "min_stay": 1
        },
        {
          "channel": "booking",
          "rate_id": "1",
          "price": 135.00,
          "currency": "USD",
          "min_stay": 2
        }
      ]
    }
  ]
}
```

**Filters:** `category_id` (single category), `channel` (filter rates by channel).

> **Note:** `channel_rates` table is populated manually or from an external channel manager — it is not scraped from OtelMS.

### Housekeeping (Limpieza)

**Cuatro tipos de limpieza, criterio basado en la fecha consultada:**

| Tipo | Criterio | Cuándo aplicar |
|------|----------|----------------|
| **Limpieza completa (full)** | `check_out == target_date` | El huésped se fue esta mañana → habitación libre, limpieza profunda |
| **Limpieza continua (continuous)** | `check_in < target_date < check_out` | El huésped pernocta → habitación ocupada, limpieza ligera |
| **Bloqueadas (blocked)** | Sin reserva activa para la fecha | Habitación libre pero bloqueada (mantenimiento, etc.) |
| **Ingresos (income_generating)** | `check_in == target_date` | Llegada nueva hoy → habitación ocupada que generará ingresos |

> **Importante:** El día de salida **no** cuenta como noche de pernocta. El huésped se va por la mañana, así que `check_out == target_date` va a "limpieza completa", no a "continuous". Las habitaciones ya marcadas como limpias (status=2) **no aparecen** en el listado.

**Endpoints:**

```bash
# Plan completo de limpieza para una fecha
GET /housekeeping?hotel_id=18330&target_date=2026-10-07

# Solo limpieza completa (check-outs de hoy)
GET /housekeeping/full-cleaning?hotel_id=18330&target_date=2026-10-07

# Solo limpieza continua (ocupadas que pernoctan)
GET /housekeeping/stay-over?hotel_id=18330&target_date=2026-10-07

# Cambiar estado de limpieza de una habitación (requiere permiso housekeeping:write)
PATCH /housekeeping/{room_id}?hotel_id=18330&target_date=2026-10-07
Content-Type: application/json
{"status": 2, "updated_by": "maria.limpieza"}

# Reiniciar todos los estados de limpieza de una fecha a pending (requiere housekeeping:write)
POST /housekeeping/reset?hotel_id=18330&target_date=2026-10-07
```

**Respuesta (`/housekeeping`):**
```json
{
  "hotel_id": "18330",
  "date": "2026-10-07",
  "full_cleaning": [
    {
      "room_id": "107",
      "room_name": "107",
      "category_id": "13",
      "category_name": "Matrimonial",
      "reservation_id": "23356",
      "guest_name": "Bejot Louis",
      "check_in": "2026-09-20T05:00:00Z",
      "check_out": "2026-10-07T05:00:00Z",
      "adults": 2,
      "children": 0,
      "nights_remaining": 0,
      "cleaning_type": "full",
      "status": 4
    }
  ],
  "continuous_cleaning": [
    {
      "room_id": "101",
      "room_name": "101",
      "category_id": "13",
      "category_name": "Matrimonial",
      "reservation_id": "23357",
      "guest_name": "Garcia Maria",
      "check_in": "2026-10-05T14:00:00Z",
      "check_out": "2026-10-10T11:00:00Z",
      "adults": 2,
      "children": 1,
      "nights_remaining": 3,
      "cleaning_type": "continuous",
      "status": 2
    }
  ],
  "blocked_rooms": [
    {
      "room_id": "205",
      "room_name": "205",
      "category_id": "15",
      "category_name": "Suite",
      "reservation_id": null,
      "guest_name": null,
      "check_in": null,
      "check_out": null,
      "adults": 0,
      "children": 0,
      "nights_remaining": 0,
      "cleaning_type": "blocked",
      "status": null
    }
  ],
  "income_generating_rooms": [
    {
      "room_id": "102",
      "room_name": "102",
      "category_id": "13",
      "category_name": "Matrimonial",
      "reservation_id": "23358",
      "guest_name": "New Guest",
      "check_in": "2026-10-07T14:00:00Z",
      "check_out": "2026-10-12T11:00:00Z",
      "adults": 2,
      "children": 0,
      "nights_remaining": 5,
      "cleaning_type": "income_generating",
      "status": 1
    }
  ],
  "total_rooms_to_clean": 17
}
```

**Casos de uso:**
- `/housekeeping` → Plan maestro para el equipo de housekeeping (recepción imprime y reparte)
- `/housekeeping/full-cleaning` → Equipo de limpieza profunda (habitaciones que quedan libres)
- `/housekeeping/stay-over` → Equipo de mantenimiento (habitaciones con huésped dentro)
- `PATCH /housekeeping/{room_id}` → App móvil/tablet de housekeeping para marcar habitaciones como limpias
- `POST /housekeeping/reset` → Recepción: reiniciar plan si hubo error o cambio de turno

### Check-in, check-out and moving a reservation

`src/otelms/scraping/checkin.py` speaks to the three reservation operations:

```python
await check_in(hotel_id, reservation_id)                    # GET  /reservation_c2/set_checkin/{id}/status
await check_out(hotel_id, reservation_id)                   # GET  /reservation_c2/set_checkout/{id}/status
await move_reservation(hotel_id, reservation_id, room_id="110")
```

`move_reservation` deliberately **does not build the request payload**. It
re-reads the form OtelMS just served and changes only the field you asked for,
so the per-night `day_price[]` values are the portal's own and never invented —
on a real reservation an invented price is a real charge. It also refuses to
move a reservation that hasn't arrived yet, because OtelMS's own check-out
form then carries a **negative duration** (measured: `-4`).

**These three are not exposed over HTTP, and none of them has been called
against the live portal.** The URLs are read from the portal HTML and the
client is covered by `tests/unit/test_checkin.py` with `httpx.MockTransport`,
but a `GET` to `set_checkin` checks a real guest into a real room and
`set_checkout` closes a real invoice. `docs/otelms_endpoints.md` §4.6 has the
full map and §5 lists them as unverified.

One thing that looks like a way to read arrival state but isn't: the folio's
`#do_checkin` / `#do_checkout` classes (`withtoggle` vs `withtoggle d0`) are
**identical for a guest who is in-house and one who hasn't arrived yet**
(§4.7). The date-range criterion from the in-house endpoint is the one that
holds.

### Building API responses

The response schemas use `from_attributes=True` over SQLAlchemy entities, which
means an unloaded relationship blows up with `MissingGreenlet` during
serialization. Rather than relying on `from_attributes` for nested schemas,
endpoints call the mappers in `src/otelms/api/mappers.py`:

```python
from otelms.api.mappers import reservation_response

reservations = await res_repo.get_by_hotel(hotel_id=hotel_id)
return [reservation_response(r) for r in reservations]
```

Two rules keep this working:

- **Eager loading lives in the repository that needs it.** The mappers only read
  relationships that are already loaded (`obj.__dict__.get(name)` never issues a
  query), so if a mapper comes back with an empty relation, the repository query
  is missing a `selectinload`. `RESERVATION_DETAIL_OPTIONS` in
  `domain/repositories/__init__.py` is the shared set for reservations.
- **Break the cycle explicitly.** `CategoryResponse.rooms` and
  `RoomResponse.category` reference each other; serializing them straight from an
  ORM entity aborts with `recursion_loop`. The mapper returns the nested category
  as a `{id, name}` stub with `rooms=[]`, which carries all the useful
  information and cannot cycle.

If you add a schema with a nested relationship, add the matching mapper and the
matching `selectinload`. `tests/unit/test_api_relation_serialization.py` covers
the current set.

### Query Parameters

```bash
# Reservations with filters
GET /reservations?hotel_id=118510&status=1&check_in_from=2026-01-01&page=1&page_size=50

# Guests with search
GET /guests?hotel_id=118510&search=John&limit=100
```

---

## 🔧 Configuration

All configuration via environment variables (`.env`):

```bash
# App
APP_ENV=production          # development|staging|production
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8000

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/otelms

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# OtelMS Credentials
OTELMS_DEFAULT_HOTEL_ID=118510
OTELMS_DEFAULT_USERNAME=gerencia@harmonyhotelgroup.com
OTELMS_DEFAULT_PASSWORD=your_password

# Scraping
SCRAPER_HEADLESS=true
SCRAPER_RATE_LIMIT_REQUESTS_PER_MINUTE=30
SCRAPER_RATE_LIMIT_BURST=5
SCRAPER_VERIFY_SSL=true
BROWSER_POOL_SIZE=2

# Security
API_KEY=your-secure-api-key-here
JWT_SECRET_KEY=your-jwt-secret-min-32-chars
```

See `.env.example` for all 80+ options.



### Roles & Permissions (RBAC)

The API uses a role-based access control system. Each API Key can be assigned one or more roles, and each role has a set of permissions.

**Default Permissions:**
| Permission | Description |
|------------|-------------|
| `housekeeping:read` | Read housekeeping plans |
| `housekeeping:write` | Update housekeeping status (PATCH/POST) |
| `reservations:read` | Read reservations |
| `reservations:write` | Create/update reservations |
| `reports:read` | Read reports |
| `reports:write` | Generate reports |
| `admin:read` | Admin read access |
| `admin:write` | Admin write access |
| `scraping:manage` | Manage scraping jobs |
| `settings:read` | Read settings |
| `settings:write` | Modify settings |

**Assigning roles to an API Key:**
```sql
-- Insert role
INSERT INTO roles (id, name, description, permissions, is_active)
VALUES ('role-1', 'housekeeper', 'Housekeeping staff', '["housekeeping:read", "housekeeping:write"]', true);

-- Link API key to role
INSERT INTO api_key_roles (id, api_key_id, role_id)
VALUES ('akr-1', 'your-api-key-id', 'role-1');
```

Endpoints requiring specific permissions will return `403 Forbidden` if the API key lacks the required permission. In development mode (`API_KEY_REQUIRED=false`), permission checks are bypassed.

### Check-in / Check-out Configuration

**Horarios por defecto (configurables en OtelMS, no en la API):**

| Evento | Hora por defecto | Dónde cambiar |
|--------|------------------|---------------|
| Check-in | 14:00 (2 PM) | OtelMS → Configuración → Hotel → Horarios |
| Check-out | 11:00 (11 AM) | OtelMS → Configuración → Hotel → Horarios |

**Impacto en la API:**
- La API lee `check_in` y `check_out` como timestamps UTC desde la BD (poblados por el scraper).
- El criterio de "noches" y "pernocta" usa **solo la parte de fecha** (`date()`).
- El día del check-out **no** cuenta como noche: `check_in <= target_date < check_out`.
- Para cambiar los horarios: edita en el portal OtelMS y espera al próximo sync (o dispara `/reservations/sync/full`).

### Browser Mode: Local vs Docker

| Entorno | Variable | Valor | Comportamiento |
|---------|----------|-------|----------------|
| **Local (desarrollo)** | `SCRAPER_HEADLESS` | `false` | Navegador visible (headful) para debugging |
| **Local (desarrollo)** | `BROWSER_HEADLESS` | `false` | Idem, alias de compatibilidad |
| **Docker (producción/CI)** | `SCRAPER_HEADLESS` | `true` | Headless obligatorio (sin display) |
| **Docker (producción/CI)** | `BROWSER_HEADLESS` | `true` | Idem |

> **Nota:** Los scripts `run-local.sh` / `run-local.ps1` crean `.env.local` con `SCRAPER_HEADLESS=false`. El `docker-compose.yml` tiene `SCRAPER_HEADLESS=true` y `BROWSER_HEADLESS=true` hardcodeados en los servicios `worker` y `beat`.

### Local Development Scripts

**Linux/macOS (`scripts/run-local.sh`):**
```bash
chmod +x scripts/run-local.sh
./scripts/run-local.sh
```

**Windows PowerShell (`scripts/run-local.ps1`):**
```powershell
.\scripts\run-local.ps1
```

**Qué hacen ambos scripts:**
1. Levantan infraestructura en Docker (PostgreSQL en 5433, Redis en 6380)
2. Ejecutan migraciones Alembic
3. Crean `.env.local` con overrides para desarrollo (puerto API 8001, headless=false, DB/Redis en puertos Docker)
4. Inician API (8001), Celery Worker y Celery Beat en background
5. Guardan PIDs en `/tmp/otelms_*.pid` (Linux) o `$env:TEMP\otelms_*.pid` (Windows)
6. Health check automático en `http://localhost:8001/health`

**Parar todo:**
```bash
# Linux/macOS
./scripts/run-local.sh stop

# Windows
.\scripts\run-local.ps1 -Stop
```

**Puertos en local:**
| Servicio | Puerto | Nota |
|----------|--------|------|
| API | 8001 | Evita conflicto con Docker (8000) y otros servicios |
| PostgreSQL | 5433 | Contenedor `otelms-postgres` |
| Redis | 6380 | Contenedor `otelms-redis` |

### Docker Deployment

**Development (docker-compose.yml):**
```bash
# Construir y levantar
docker compose -f docker/docker-compose.yml up -d --build

# Ver logs
docker compose -f docker/docker-compose.yml logs -f api
docker compose -f docker/docker-compose.yml logs -f worker

# Escalar workers
docker compose -f docker/docker-compose.yml up -d --scale worker=3
```

**Production (con Nginx):**
```bash
docker compose -f docker/docker-compose.yml --profile production up -d
```

**Puertos en Docker:**
| Servicio | Puerto (host) | Puerto (contenedor) |
|----------|---------------|---------------------|
| API | 8000 | 8000 |
| PostgreSQL | 5432 | 5432 |
| Redis | 6379 | 6379 |

**Variables clave en `docker-compose.yml`:**
- `worker` y `beat`: `SCRAPER_HEADLESS=true`, `BROWSER_HEADLESS=true`
- `api`: `SCRAPER_HEADLESS=true` (no usa browser pero hereda config)
- Volúmenes: `../src:/app/src:ro` (código montado read-only para hot-reload en API)

**Podman en WSL2 (sin bridge nftables):**
```bash
DOCKER_HOST=npipe:////./pipe/podman-machine-default \
docker compose -f docker/docker-compose.yml -f docker/docker-compose.podman.yml up -d
```
Usa `network_mode: host` con puertos: PostgreSQL 5434, Redis 6381, API 8011.

---

## 🧪 Testing

```bash
# Run all tests
python scripts/run_tests.py

# Or individually
uv run pytest tests/unit -v              # Unit tests
uv run pytest tests/integration -v       # Integration tests
uv run pytest tests/e2e -v               # E2E API tests
uv run pytest tests/unit --cov=src/otelms # With coverage

# Linting
uv run ruff check .
uv run ruff format --check .
uv run mypy src/otelms
```

### Test Structure

```
tests/
├── unit/                    # Fast, isolated tests
│   ├── test_parsers.py      # HTML parser tests
│   └── test_repositories.py # Repository CRUD tests
├── integration/             # DB/Redis required
│   ├── test_sync_service.py # Sync service tests
│   └── test_api_contracts.py # API contract tests
├── e2e/                     # End-to-end API tests (ASGI transport)
│   ├── test_health.py       # Health check endpoints
│   ├── test_api_auth.py     # Authentication & rate limiting
│   ├── test_hotels.py       # Hotel management endpoints
│   └── test_reservations.py # Reservation endpoints
└── conftest.py              # Pytest fixtures
```

---

## 📦 Project Structure

```
scraping_otelms_api/
├── .github/workflows/       # CI/CD
├── docker/                  # Docker files
│   ├── Dockerfile           # Unified multi-stage (targets: api, worker, beat)
│   └── docker-compose.yml   # Full stack
├── migrations/              # Alembic migrations
├── scripts/                 # Utility scripts
├── src/otelms/
│   ├── api/                 # FastAPI layer
│   │   ├── main.py          # App factory
│   │   ├── dependencies.py  # DI container
│   │   ├── schemas.py       # Pydantic models
│   │   └── routes/          # API endpoints
│   ├── config/              # Settings & constants
│   ├── domain/              # Domain layer
│   │   ├── models/          # API contracts (Pydantic)
│   │   ├── entities/        # DB models (SQLAlchemy)
│   │   └── repositories/    # Data access
│   ├── scraping/            # Scraping engine
│   │   ├── browser.py       # Camoufox pool
│   │   ├── auth.py          # Login & session
│   │   ├── rate_limiter.py  # Token bucket
│   │   ├── retry.py         # Retry policies
│   │   ├── extractors/      # Page extractors
│   │   ├── parsers/         # HTML parsers
│   │   └── orchestrator.py  # Main pipeline
│   ├── services/            # Business logic
│   │   └── sync_service.py  # Scraping → DB sync
│   ├── tasks/               # Celery tasks
│   │   ├── celery_app.py    # Celery config
│   │   └── scraping_tasks.py # Scheduled tasks
│   └── utils/               # Shared utilities
│       ├── logging.py       # Structlog setup
│       ├── cache.py         # Redis/diskcache
│       └── telemetry.py     # OpenTelemetry
├── tests/                   # Test suite
├── pyproject.toml           # Project config
├── alembic.ini              # Migrations config
└── .env.example             # Env template
```

---

## 🔄 Sync Operations

### Automatic (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| `sync_calendar` | Every 15 min | Calendar grid sync |
| `sync_categories` | Hourly | Categories & rooms |
| `sync_full` | Daily 3 AM | Complete sync |

### Manual via API

```bash
# Calendar sync
curl -X POST -H "X-API-Key: $KEY" \
  "http://localhost:8000/reservations/sync/calendar?hotel_id=118510&target_date=2026-01-15"

# Full sync
curl -X POST -H "X-API-Key: $KEY" \
  "http://localhost:8000/reservations/sync/full?hotel_id=118510"
```

### CLI

```bash
# One-off sync
otelms sync --hotel-id 118510 --full

# Scraping only (no DB)
otelms scraper --hotel-id 118510 --strategy calendar --date 2026-01-15
```

---

## 📊 Monitoring

### Prometheus Metrics

```
GET /metrics
```

Key metrics:
- `otelms_http_requests_total` - Request count by endpoint/status
- `otelms_http_request_duration_seconds` - Latency histogram
- `otelms_scraping_operations_total` - Scraping ops by type/status
- `otelms_scraping_duration_seconds` - Scraping latency
- `otelms_sync_records_processed_total` - Records created/updated
- `otelms_celery_tasks_total` - Background task stats
- `otelms_active_browsers` - Browser pool usage

### Structured Logs

```json
{
  "timestamp": "2026-01-15T10:30:00.123Z",
  "level": "INFO",
  "logger": "otelms.scraping.orchestrator",
  "message": "Calendar scraping completed",
  "hotel_id": "118510",
  "operation": "calendar",
  "duration_ms": 2341,
  "records_processed": 45
}
```

### Health Checks

```bash
# Liveness (process alive)
curl http://localhost:8000/health/live

# Readiness (dependencies ready)
curl http://localhost:8000/health/ready

# Full health
curl http://localhost:8000/health
```

---

## 🐳 Deployment

### Production Docker Compose

```bash
# Production profile with Nginx
docker compose -f docker/docker-compose.yml --profile production up -d

# Scale workers
docker compose up -d --scale worker=3
```

### Unified Dockerfile

The project uses a single multi-stage `docker/Dockerfile` with targets:
- `api` — FastAPI + Uvicorn (no browser)
- `worker` — Celery worker + Camoufox/Playwright
- `beat` — Celery Beat scheduler

All targets share base/deps/camoufox layers for efficient builds.

### Podman on WSL2

For WSL2 environments with kernel nftables issues, use the Podman override:

```bash
DOCKER_HOST=npipe:////./pipe/podman-machine-default \
docker compose -f docker/docker-compose.yml -f docker/docker-compose.podman.yml up -d
```

This uses `network_mode: host` with custom ports (5434 PostgreSQL, 6381 Redis, 8011 API).

### Kubernetes (Helm values example)

```yaml
replicaCount: 2
image:
  repository: otelms-api
  tag: latest
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: otelms-secrets
        key: database-url
  - name: REDIS_URL
    value: "redis://redis:6379/0"
resources:
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

---

## 🔐 Security Considerations

- **API Keys**: Rotate regularly, use strong random values (32+ chars)
- **JWT Secret**: Minimum 32 characters, store in secret manager
- **Database**: Use SSL connections, restrict network access
- **Redis**: Enable authentication, use TLS in production
- **Rate Limiting**: Configure per your infrastructure capacity
- **Credentials**: Never commit `.env` - use secret management
- **Scraping**: Only run against authorized properties

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`python scripts/run_tests.py`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open Pull Request

### Code Style

- **Ruff** for linting/formatting (`ruff check . && ruff format .`)
- **MyPy** for type checking (`mypy src/otelms`)
- **Pre-commit** hooks configured

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## ⚠️ Legal Disclaimer

This software is provided for educational and authorized use only. The authors:

- **Do not endorse** scraping without explicit permission
- **Are not responsible** for any legal consequences of misuse
- **Recommend** reviewing OtelMS Terms of Service before use
- **Advise** obtaining written authorization from property owners

Use responsibly and ethically.

---

## 🙏 Acknowledgments

- [Camoufox](https://github.com/daijro/camoufox) - Anti-detect browser
- [FastAPI](https://fastapi.tiangolo.com) - Modern web framework
- [SQLAlchemy](https://sqlalchemy.org) - Database toolkit
- [Celery](https://docs.celeryq.dev) - Distributed task queue
- [Playwright](https://playwright.dev) - Browser automation
- [structlog](https://www.structlog.org) - Structured logging

---

**Built with ❤️ for Harmony Hotel Group**