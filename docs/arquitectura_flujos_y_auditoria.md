# Arquitectura, Flujos de Scraping y Auditoría de Endpoints — OtelMS API (`18330`)

**Fecha de auditoría:** 2026-11-13  
**Alcance operativo:** Hotel único `18330` (*Hotel Ensueños by HHG*)  
**Objetivo del documento:** Documentar de dónde y cómo se extrae actualmente la información, listar los errores reales observados en base de datos y respuestas, inventariar los **74 endpoints HTTP** (+ WebSocket) actuales y proponer un **API Gateway por etapas (Fase 1: Lectura/Extracción vs. Fase 2: Escritura/Interacción)**.

---

## 1. Arquitectura Actual del Sistema

El proyecto sigue una arquitectura en 4 capas con **dos motores de sincronización paralelos** (deuda técnica heredada):

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. CAPA API (FastAPI - src/otelms/api/main.py)                          │
│    • 74 endpoints HTTP + 1 WebSocket (/ws/{hotel_id})                   │
│    • Auth: X-API-Key (sha256 en tabla api_keys / fallback .env)         │
│    • Middlewares: CORS, RateLimit (Redis), Prometheus (/metrics)        │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. CAPA SERVICIOS & COLAS                                               │
│    • SyncService (async - src/otelms/services/sync_service.py)          │
│    • SetupSyncService (async - src/otelms/services/setup_sync_service.py)│
│    • CalendarSyncService (sync legacy - calendar_sync_service.py)       │
│    • Celery + Beat (src/otelms/tasks/celery_app.py & scraping_tasks.py) │
├─────────────────────────────────────────────────────────────────────────┤
│ 3. CAPA SCRAPING (src/otelms/scraping/)                                 │
│    • Camino Principal: HTTP directo (httpx + cookies de sesión OtelMS)  │
│    • Camino Fallback: Browser (Playwright / Camoufox en browser.py)     │
│    • Parsers: BeautifulSoup + regex (calendar_markup_v2, folio_extract, │
│               folio_deep_extract, setup_extract, restrictions)          │
├─────────────────────────────────────────────────────────────────────────┤
│ 4. CAPA PERSISTENCIA (SQLite local: otelms.db / Postgres en Docker)     │
│    • 21 tablas de negocio + alembic_version                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Autenticación interna contra OtelMS (Flujo "oculto" de sesión)
No existe un endpoint público de login de OtelMS en nuestra API; el sistema se autentica internamente de forma automática:
1. `src/otelms/scraping/auth.py` (`get_authenticated_http_session(hotel_id)`) hace `GET` a `/login_c2/single_login?hmsid=18330` y `POST` a `/login_c2/do_single_login` con `hotel`, `login`, `password`, `action=login` (leídos de `.env` o descifrados con Fernet desde `hotels.encrypted_password`).
2. Captura la cookie de sesión PHP/CodeIgniter de OtelMS en un `httpx.AsyncClient` persistente.
3. Si una respuesta redirige a `login`, invalida y renueva la sesión.

---

## 2. Flujos Actuales de Extracción (Origen → Extractor → BD)

| # | Fuente OtelMS (URL) | Datos que aporta | Extractor / Parser | Método | Tabla(s) destino en `otelms.db` | Estado real observado |
|---|---|---|---|---|---|---|
| 1 | `/setup_property_c2/property_information` | Datos de empresa (nombre, legal, dirección, GPS, teléfono, email, horarios check-in/out) | `SetupExtractor.extract_property_information()` (`setup_extract.py`) | HTTP (`httpx`) | `hotels` | **OK** (`18330` poblado; pero existe registro basura `test_hotel_e2e_new`) |
| 2 | `/setup_property_c2/property_description` | Amenidades y servicios activos del hotel | `SetupExtractor.extract_property_description()` (`setup_extract.py`) | HTTP (`httpx`) | `property_services` (42 filas) | **OK** |
| 3 | `/setup_payment_types_c2/type_list/1` | Catálogo maestro de métodos de pago | `SetupExtractor.extract_payment_types()` (`setup_extract.py`) | HTTP (`httpx`) | `payment_methods` (8 filas) | **OK** |
| 4 | `/setup_dealers_c2/dealers_list/1` | Fuentes / canales de venta | `SetupExtractor.extract_dealers()` (`setup_extract.py`) | HTTP (`httpx`) | `dealers` (8 filas) | **OK** |
| 5a | `/setup_categories_c2/categories_list` | Categorías oficiales de habitación | `SetupExtractor.extract_categories()` (`setup_extract.py`) | HTTP (`httpx`) | `categories` (9 filas) | **OK** (pero `calendar_sync` también hace upsert desde el calendario y puede mezclar) |
| 5b | `/setup_rooms_c2/room_list/1` | Habitaciones físicas y relación con categoría | `SetupExtractor.extract_rooms()` (`setup_extract.py`) | HTTP (`httpx`) | `rooms` (33 filas) | **OK** |
| 6 | `/reservation_c2/price_calendar` | Precios generales por categoría, canal y fecha | `SetupExtractor.extract_price_calendar()` (`setup_extract.py`) | HTTP (`httpx`) | **`channel_rates` (0 filas)** | **INCOMPLETO:** solo responde en vivo por endpoint; **no persiste** en `channel_rates` |
| 7a | `/reservation_c2/calendar` | Grilla de reservas, habitaciones bloqueadas (`bg_padlock`) y disponibilidad por categoría (`calendar_sum`) | `fetch_calendar_html()` + `CalendarParser.parse_grid()` → `calendar_markup_v2.py` | HTTP (`httpx`) / Fallback Browser | `reservations` (50), `guests` (55), `category_availability` (414) | **CON BUGS:** guarda `balance` negativo en `total_price`; `room_availability` queda en 0 filas |
| 7b | `/reservation_c2/status` | Escritorio operativo: llegadas, salidas y alojados de hoy | `SetupExtractor.extract_status()` (`setup_extract.py`) | HTTP (`httpx`) | Sin tabla (lectura en vivo) | **PARCIAL:** `GET /hotels/{id}/status` consulta en vivo, mientras `/reservations/today/*` y `/in-house` leen BD local |
| 8 | `/reservation_c2/folio/{id}/1` | Detalle completo: cliente, fuente, fechas, noches, huéspedes, pagos, servicios, vehículo, notas, datos OTA, tarifa por noche, historial de cambios | `FolioClient` + `parse_folio()` (`folio_extract.py`) + `parse_folio_complete()` (`folio_deep_extract.py`) | HTTP (`httpx`) | `reservations`, `services` (352), `payments` (31), `reservation_night_rates` (54), `reservation_change_history` (310) | **CON BUGS:** ver sección 3 (32/50 reservas con datos deep, campos desplazados/rotos) |
| 9 | `/reservation_c2/restrict_calendar` | Fechas cerradas por categoría y tarifa | `restrictions.py` (`get_restrictions`) | HTTP (`httpx`) | Sin tabla (en vivo) | **OK** (solo lectura en vivo) |

---

## 3. Errores y Fallos Reales Detectados (Verificados en `otelms.db` y código)

### Bug 1 (Crítico): `total_price` negativo en 39 de 50 reservas
- **Evidencia en `otelms.db`:** Reservas como `23626`, `23625` (`-103`), `23624` (`-153`), `23297` (`-64.02`), `23299` (`-80`), `23620` (`-72`) tienen `total_price` negativo.
- **Causa raíz:** En `src/otelms/services/sync_service.py`:
  - Línea `632`: `"total_price": cell.get("balance")`
  - Línea `905`: `"total_price": _pick(detail, "total", "balance")`
  En OtelMS, `Saldo` (`balance`) es negativo cuando el huésped debe dinero (ej. `Saldo: -64.02`). Al no existir `total` en la celda del calendario ni en `parse_folio_complete`, el sistema guarda el saldo deudor como si fuera el precio total de la reserva.

### Bug 2 (Crítico): `channel_phone` captura el nombre del siguiente campo cuando está vacío
- **Evidencia en vivo (Folio `23641`):** `parse_folio_complete()` devuelve:
  `'channel_phone': 'Número de la tarjeta de huésped:'`
- **Causa raíz:** En `src/otelms/scraping/folio_deep_extract.py` (líneas `113-127`), la extracción del panel *"Información desde el canal"* usa `panel.get_text(" | ", strip=True)` con regex `r"Teléfono de huésped:\s*\|\s*([^|]+)"`. Cuando el teléfono está vacío en el HTML, el siguiente texto separado por `|` es la etiqueta `"Número de la tarjeta de huésped:"` y el regex la captura como valor. El mismo patrón afecta potencialmente a `channel_guest_name` y `channel_reservation_id`.

### Bug 3 (Alto): Tabla `reservation_change_history` pierde `event_type`, `amount` y pega palabras en `description`
- **Evidencia en `otelms.db`:** Las **310 filas** en `reservation_change_history` tienen `event_type = 'change'` y `amount = None`, y descripciones como `'statusantes de:Check in; después de:Check out;'`.
- **Causa raíz:**
  1. Panel 15 (*Historia de los cambios*) tiene **7 columnas**: `[0] Fecha y hora | [1] № | [2] Usuario | [3] Tipo | [4] Acción | [5] Cantidad | [6] Descripción`.
  2. `folio_deep_extract.py` (líneas `284-291`) omite `h_cells[3]` (`type`) y `h_cells[5]` (`amount`), y `sync_service.py` (línea `977`) cae en el default `h.get("type") or "change"`.
  3. Además, `td.get_text(strip=True)` en celdas con sub-etiquetas HTML pega `"status"` + `"antes de:"` sin espacio.

### Bug 4 (Alto): Duplicación de noches en `services` y pérdida parcial de fechas
- **Evidencia en `otelms.db`:** Existen **352 filas** en `services` que mezclan servicios reales (ej. `23564-49842 Alojamiento`, `IVA(15%)`) con filas sintéticas por noche (`23564-night-2026-10-09`), duplicando la información que ahora vive en `reservation_night_rates` (54 filas).
- **Causa raíz:** `SyncService._service_rows()` (`sync_service.py:783-794`) sigue generando una fila `Service` por cada entrada de `room_charges`. Adicionalmente, la fila `Alojamiento` de la tabla de servicios de OtelMS viene con fecha vacía (`date: ''`) y hereda artificialmente `first_night`.

### Bug 5 (Alto): Tablas vacías y registros de prueba en `otelms.db`
- `channel_rates`: **0 filas** (el endpoint `/hotels/{id}/price-calendar` scrapea en vivo y no guarda).
- `housekeeping_status`: **0 filas** (sin flujo automático de inicialización diaria).
- `room_availability`: **0 filas** (bloqueos del calendario `bg_padlock` se detectan en el parser pero no se persisten).
- `hotels`: contiene un registro de prueba residual (`id = 'test_hotel_e2e_new'`, `E2E Test Hotel`).
- Cobertura parcial de folios profundos: solo **32 de 50** reservas tienen `night_rates` y `change_history` sincronizados.

### Bug 6 (Medio): Valores `"0"` literales en lugar de `None`
- **Evidencia en `otelms.db`:** 26 de 50 reservas tienen `channel_reservation_id = '0'` y `room_reservation_id = '0'`; 6 reservas tienen `notes = '0'`. OtelMS usa `"0"` cuando no hay dato OTA o notas y el parser/sync no lo normaliza a `None`.

### Bug 7 (Rendimiento y Arquitectura): Latencia de 5s por request sin Redis + Sync duplicado
- **Evidencia en ejecución:** Cada llamada HTTP al API cuando Redis no está activo espera `redis_socket_connect_timeout=5` segundos en `rate_limit_middleware` (`src/otelms/api/main.py:165-182`) antes de hacer fallback y permitir la petición (`Rate limiter error, allowing request error='Timeout connecting to server'`).
- **Código duplicado:** Conviven `CalendarSyncService` (`requests` síncrono) y `SyncService` (`httpx` asíncrono + Playwright) haciendo tareas solapadas con lógicas distintas.

---

## 4. Inventario Completo de Endpoints Actuales (74 HTTP + 1 WS) y Clasificación

Para ordenar el API en etapas (**Fase 1: Solo extracción/lectura** vs **Fase 2: Interacción/escritura**), cada endpoint se clasifica en:
- **`[F1-CORE]`**: Necesario en Fase 1 (consulta de datos o lectura en vivo).
- **`[INTERNO]`**: Endpoints operativos del sistema (health, métricas, triggers de sync, auth).
- **`[F2-WRITE]`**: Escritura / mutación hacia OtelMS o gestión operativa (activar en Fase 2).
- **`[ELIMINAR/OCULTAR]`**: Redundante, admin genérico peligroso o innecesario para hotel único.

### 4.1 Salud y Sistema (`/` , `/health`, `/metrics`, `/ws`)
| Método | Ruta | Qué muestra / hace | Clasificación |
|---|---|---|---|
| `GET` | `/` | Info básica del servicio | `[F1-CORE]` |
| `GET` | `/health` | Estado de BD, caché (Redis) y readiness | `[INTERNO]` |
| `GET` | `/metrics` | Métricas Prometheus en texto plano | `[INTERNO]` |
| `WS` | `/ws/{hotel_id}` | Notificaciones en tiempo real de sync | `[INTERNO]` |

### 4.2 Hotel y Maestros (`/hotels`) — 11 endpoints
| Método | Ruta | Qué muestra / hace | Clasificación |
|---|---|---|---|
| `GET` | `/hotels` | Lista hoteles en BD (incluye `test_hotel_e2e_new`) | `[ELIMINAR/OCULTAR]` (solo hay 1 hotel: `18330`) |
| `POST` | `/hotels` | Crea un nuevo hotel en BD | `[ELIMINAR/OCULTAR]` |
| `GET` | `/hotels/{hotel_id}` | Información completa de la propiedad `18330` | `[F1-CORE]` |
| `PATCH` | `/hotels/{hotel_id}` | Actualiza configuración/credenciales del hotel | `[F2-WRITE]` |
| `POST` | `/hotels/{hotel_id}/rotate-password` | Rota contraseña cifrada del hotel | `[INTERNO]` |
| `GET` | `/hotels/{hotel_id}/dealers` | Lista canales/fuentes de venta desde BD | `[F1-CORE]` |
| `GET` | `/hotels/{hotel_id}/payment-methods` | Lista métodos de pago desde BD | `[F1-CORE]` |
| `GET` | `/hotels/{hotel_id}/services` | Lista amenidades/servicios del hotel desde BD | `[F1-CORE]` |
| `GET` | `/hotels/{hotel_id}/status` | Estado operativo en vivo (`/reservation_c2/status`) | `[F1-CORE]` |
| `GET` | `/hotels/{hotel_id}/price-calendar` | Tarifas por canal en vivo (`/reservation_c2/price_calendar`) | `[F1-CORE]` |
| `POST` | `/hotels/{hotel_id}/sync-setup` | Ejecuta `SetupSyncService` (maestros a BD) | `[INTERNO]` |

### 4.3 Categorías y Habitaciones (`/categories`, `/rooms`) — 9 endpoints
| Método | Ruta | Qué muestra / hace | Clasificación |
|---|---|---|---|
| `GET` | `/categories` | Categorías oficiales con habitaciones | `[F1-CORE]` |
| `GET` | `/categories/{category_id}` | Detalle de una categoría | `[F1-CORE]` |
| `GET` | `/categories/{category_id}/rooms` | Habitaciones de una categoría | `[F1-CORE]` |
| `GET` | `/rooms` | Listado paginado de habitaciones físicas | `[F1-CORE]` |
| `GET` | `/rooms/available` | Disponibilidad calculada por reservas en BD | `[ELIMINAR/OCULTAR]` (redundante con `/available/enhanced` y `/available-for-sale`) |
| `GET` | `/rooms/available/enhanced` | Disponibilidad real usando `category_availability` de OtelMS | `[F1-CORE]` |
| `GET` | `/rooms/available-for-sale` | Habitaciones disponibles filtrando por housekeeping | `[F1-CORE]` (o fusionar con `/available/enhanced`) |
| `GET` | `/rooms/occupied` | Habitaciones ocupadas en una fecha | `[F1-CORE]` |
| `GET` | `/rooms/checkouts` | Salidas en una fecha | `[F1-CORE]` |

### 4.4 Reservas y Huéspedes (`/reservations`, `/guests`) — 16 endpoints
| Método | Ruta | Qué muestra / hace | Clasificación |
|---|---|---|---|
| `GET` | `/reservations` | Listado paginado/filtrado de reservas en BD | `[F1-CORE]` |
| `GET` | `/reservations/{reservation_id}` | Detalle completo (huésped, habitación, servicios, pagos, night_rates, historial) | `[F1-CORE]` |
| `GET` | `/reservations/in-house` | Huéspedes alojados actualmente | `[F1-CORE]` |
| `GET` | `/reservations/today/checkins` | Llegadas de hoy desde BD | `[F1-CORE]` |
| `GET` | `/reservations/today/checkouts` | Salidas de hoy desde BD | `[F1-CORE]` |
| `GET` | `/reservations/pending-charges` | Reservas con saldo pendiente | `[F1-CORE]` |
| `GET` | `/guests` | Listado de huéspedes en BD | `[F1-CORE]` |
| `GET` | `/guests/{guest_id}` | Detalle de huésped | `[F1-CORE]` |
| `POST` | `/guests` | Crea huésped manual en BD | `[F2-WRITE]` |
| `POST` | `/reservations/{reservation_id}/sync-deep` | Scrapea y guarda folio profundo de 1 reserva | `[INTERNO]` |
| `POST` | `/reservations/sync/calendar` | Dispara sync de calendario | `[INTERNO]` |
| `POST` | `/reservations/sync/categories` | Dispara sync de categorías | `[INTERNO]` |
| `POST` | `/reservations/sync/full` | Dispara sync completo | `[INTERNO]` |
| `POST` | `/reservations/sync/{hotel_id}` | Dispara sync por hotel | `[INTERNO]` (redundante) |
| `POST` | `/reservations/sync/all` | Dispara sync multi-hotel | `[ELIMINAR/OCULTAR]` (solo 1 hotel) |
| `GET` | `/reservations/sync/history` | Historial de `sync_logs` | `[INTERNO]` |

### 4.5 Restricciones y Housekeeping (`/restrictions`, `/housekeeping`) — 4 endpoints
| Método | Ruta | Qué muestra / hace | Clasificación |
|---|---|---|---|
| `GET` | `/restrictions` | Fechas cerradas por categoría/tarifa en vivo desde OtelMS | `[F1-CORE]` |
| `GET` | `/housekeeping` | Estado de limpieza diario | `[F1-CORE]` (Fase 1 lectura) |
| `PATCH` | `/housekeeping/{room_id}` | Cambia estado de limpieza | `[F2-WRITE]` |
| `POST` | `/housekeeping/reset` | Reinicia estados de limpieza | `[F2-WRITE]` |

### 4.6 Panel Admin (`/admin/*`) — 34 endpoints
Incluye:
- `/admin/login`, `/admin/api/stats`, `/admin/api/sync`, `/admin/api/sync-logs`, `/admin/api/config*`, `/admin/api/api-keys*`: **`[INTERNO]`** (útil solo si se usa el dashboard interno).
- `/admin/api/tables/{table_slug}` (`GET`, `POST`, `PUT`, `DELETE`): **`[ELIMINAR/OCULTAR]`** (CRUD genérico directo sobre tablas SQL).
- `/admin/api/tasks/close-dates`, `/admin/api/tasks/open-dates`, `/admin/api/tasks/move-reservation`: **`[F2-WRITE]`** (acciones directas sobre OtelMS para Fase 2).
- `/admin/api/tasks/availability`, `/guests`, `/reservations`, `/notifications`, `/calendar/*`: **`[ELIMINAR/OCULTAR]`** (duplican los endpoints principales).

---

## 5. Propuesta de API Gateway y Arquitectura por Etapas

Para evitar exponer 74 endpoints innecesarios y controlar manualmente qué se activa en **Fase 1 (Extracción/Información)** y qué se habilita en **Fase 2 (Interacción con OtelMS)**:

### 5.1 Gateways / Feature Flags configurables en `.env` (`settings.py`)
Agregar banderas booleanas de activación manual por módulo en `Settings`:

```ini
# --- API Gateway / Control de Endpoints ---
API_ENABLE_READ_PUBLIC=true       # [F1-CORE] GET de consulta (hotels, categories, rooms, reservations, guests, restrictions)
API_ENABLE_INTERNAL_SYNC=true     # [INTERNO] /health, /metrics, /sync-setup, /sync-deep, /sync/full
API_ENABLE_WRITE_ACTIONS=false    # [F2-WRITE] POST/PATCH/DELETE que mutan OtelMS o BD operativa (close-dates, move-reservation, housekeeping PATCH)
API_ENABLE_ADMIN_ROUTES=false     # Panel /admin y CRUDs administrativos
API_ENABLE_LEGACY_ROUTES=false    # Rutas redundantes (/rooms/available, /reservations/sync/all, etc.)
```

### 5.2 Cómo operaría el Gateway en `create_app()` (`src/otelms/api/main.py`)
1. **Montaje condicional por etapa:** Si `API_ENABLE_ADMIN_ROUTES=false`, el router `admin.router` ni siquiera se monta en OpenAPI (`/docs`).
2. **Middleware Gateway por método/prefijo:** Un `GatewayMiddleware` centralizado verifica para cada request entrante si el grupo del endpoint está habilitado; si está desactivado (por ejemplo un `POST`/`PATCH` de Fase 2), responde `503 Service Unavailable` o `403 Endpoint disabled in current API stage` de forma uniforme, **sin borrar el código de Fase 2**.
3. **Separación de rutas internas (Sync / Auth):** Los endpoints `[INTERNO]` (`sync-setup`, `sync-deep`, `sync/full`, `api-keys`) deben exigir un rol/scope de sistema (`admin:sync`) distinto de la `API_KEY` de solo lectura que consumen los clientes externos en Fase 1.

---

## 6. Plan de Corrección Inmediato (Priorizado)

1. **Corregir Bugs de Datos en Scraping/Sync (Fase 1):**
   - Arreglar `total_price` en `sync_service.py` (extraer `Total` real de servicios/alojamiento y separar `balance` como saldo, no sobrescribir `total_price` con saldo negativo).
   - Arreglar regex del panel *"Información desde el canal"* en `folio_deep_extract.py` para no capturar el siguiente label cuando un campo viene vacío, y normalizar `"0"` → `None`.
   - Corregir columnas de `tbl_history` en `folio_deep_extract.py` para extraer `event_type` (col 3), `amount` (col 5) y separar palabras en `description`.
   - Dejar de duplicar `room_charges` dentro de `services` (ya viven en `reservation_night_rates`).
   - Persistir `price_calendar` en `channel_rates` y eliminar `test_hotel_e2e_new` de `hotels`.
2. **Corregir Latencia de Redis en `rate_limit_middleware`:**
   - Usar circuito corto / in-memory fallback cuando Redis no esté disponible para eliminar la espera de 5s por request.
3. **Implementar Gateway de Endpoints por Etapas (`.env` flags):**
   - Activar solo **~20 endpoints `[F1-CORE]`** para consumo externo en Fase 1, mantener **`[INTERNO]`** protegido para el worker/operación, y dejar **`[F2-WRITE]`** apagado hasta iniciar la Fase 2.
