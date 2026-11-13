# Plan de Cambios y Correcciones — OtelMS API (`18330`)

Este plan integra las **4 observaciones del usuario** junto con los **fallos reales detectados en la auditoría de `otelms.db` y ejecución en vivo**.

---

## 1. Explicación de las Observaciones Previas

### 1.1 Errores visibles en la terminal durante `full_sync` + `SetupSyncService`
Aunque `sync_logs` registró `status='completed'`, en la terminal aparecieron **4 errores/warnings reales**:
1. **Timeout de Redis (`Rate limiter ping failed error='Timeout connecting to server'`)**: Al no haber servidor Redis activo en `localhost:6379`, el rate limiter y el middleware HTTP esperan 5s hasta agotar el timeout.
2. **Fallo de login eager en Camoufox/Scrape.do (`Login failed: All connection attempts failed` / `Eager browser login failed`)**: `SyncService.initialize()` levanta `ScrapingOrchestrator` con 2 navegadores Playwright/Camoufox usando `Scrape.do` e intenta un login anticipado que falla, consumiendo ~15s y ensuciando el log con `[error]`, cuando **`full_sync()` ni siquiera usa navegador** (va 100% por `httpx`).
3. **Desconexión remota sin reintento (`httpx.RemoteProtocolError: Server disconnected without sending a response`)**: Ocurrió en `SetupExtractor.extract_categories()` porque `SetupExtractor` no tiene política de reintentos (`retry`/backoff) ni `timeout` explícito ante cortes del servidor OtelMS.
4. **Excepción en destructor de subproceso en Windows (`ValueError: I/O operation on closed pipe`)**: Provocada por el cierre del pool de Camoufox/Playwright al finalizar `asyncio.run()`.

### 1.2 Qué sincroniza actualmente `SetupSyncService`
[`SetupSyncService`](file:///d:/Coders/00_activos/scraping_otelms_api/src/otelms/services/setup_sync_service.py) llama a `SetupExtractor.extract_all_setup()` y sincroniza **6 páginas maestras de configuración** en BD:
1. `/setup_property_c2/property_information` → **`hotels`**: nombre, razón social, tipo, dirección, ciudad, provincia, país, código postal, GPS, teléfono, email, web, estrellas, horarios check-in/out y zona horaria.
2. `/setup_property_c2/property_description` → **`property_services`**: catálogo de amenidades/servicios activos del hotel *(actualmente roto: guarda `amenity_types[{amenity_id}]` en las 42 filas)*.
3. `/setup_payment_types_c2/type_list/1` → **`payment_methods`**: 8 métodos de pago configurados *(6 de ellos con `type='?'`)*.
4. `/setup_dealers_c2/dealers_list/1` → **`dealers`**: 8 canales/fuentes de venta (Venta directa, Booking, Expedia, Google Hotels, AirBnB, etc.).
5. `/setup_categories_c2/categories_list` → **`categories`**: 9 categorías oficiales (`13`–`21`) con `sort_order`.
6. `/setup_rooms_c2/room_list/1` → **`rooms`**: 33 habitaciones físicas vinculadas a su `category_id` *(actualmente `floor=''` y `max_occupancy=NULL`)*.

---

## 2. Plan de Cambios y Correcciones

### Fase A — Programación de Tareas y Alcance de `sync_full` (Celery + `SyncService`)
1. **Eliminar `sync-categories-hourly` de Celery Beat** (`src/otelms/tasks/celery_app.py`):
   - Dejar solo `sync-calendar-every-15-min` (operativo frecuente) y `sync-full-daily` (1 vez al día).
2. **Ampliar `SyncService.full_sync()`** (`src/otelms/services/sync_service.py`):
   - Ejecutar en orden:
     1. **Setup / Categorías y Maestros** (`SetupSyncService` o categorías/habitaciones oficiales).
     2. **Calendario + Bloqueos + Disponibilidad** (`sync_calendar`, persistiendo también bloqueos `bg_padlock` en `room_availability`).
     3. **Precios por canal (`price_calendar`)**: extraer `/reservation_c2/price_calendar` y persistir en la tabla **`channel_rates`** (actualmente con 0 filas).
     4. **Restricciones (`restrict_calendar`)**: extraer `/reservation_c2/restrict_calendar` y persistir en tabla **`restrictions`** (o caché/snapshot diario para consulta rápida sin golpear OtelMS en cada GET).
     5. **Estado operativo + Housekeeping**: consultar `/reservation_c2/status` (para actualizar el estado real de check-in/check-out del día en `reservations`) e inicializar/actualizar **`housekeeping_status`** diario.
     6. **Folios profundos (`sync_reservation_details`)**: sincronizar todas las reservas activas/próximas del calendario.
3. **Eliminar arranque eager de Playwright/Camoufox en `SyncService.initialize()`**:
   - Hacer **lazy** la inicialización de `ScrapingOrchestrator` (solo abrir navegador si el flujo HTTP falla y requiere fallback real), eliminando los errores `[error] Login failed` y el overhead de 15s + cierre de pipes en Windows.
4. **Agregar reintentos HTTP en `SetupExtractor` y `FolioDeepExtractor`**:
   - Implementar retry con backoff exponencial (2-3 intentos) ante `httpx.RemoteProtocolError` / `TimeoutException`.

### Fase B — Corrección de Extractores y Calidad de Datos en BD
1. **Tabla de auditoría de HTML crudo (`raw_scrape_snapshots`)** *(si se aprueba)*:
   - Crear entidad `RawScrapeSnapshot` (`id`, `hotel_id`, `source_type`, `source_key`, `url`, `html_content`, `content_hash`, `scraped_at`) para guardar el HTML completo de calendario, folios y setup, permitiendo auditar y re-parsear sin volver a golpear OtelMS.
2. **Corregir `total_price` negativo en `reservations`** (`sync_service.py:632, 905`):
   - Separar el saldo deudor (`balance`) del precio total (`total_price`). Calcular/extraer `total_price` real sumando cargos de `services` (o `Alojamiento` + servicios) y evitar guardar `balance` negativo en `total_price`.
3. **Corregir `guests` vacíos (0% teléfono/email/documento)** (`sync_service.py` + `folio_deep_extract.py` + `folio_extract.py`):
   - En `_persist_reservation_details()`, actualizar la fila existente en `guests` con `phone`, `email`, `gender`, `birth_date`, `nationality` extraídos del folio (y del tab de huéspedes).
4. **Corregir `property_services` (42 filas con `{amenity_id}`)** (`setup_extract.py`):
   - Inspeccionar el HTML real de `/setup_property_c2/property_description` para filtrar plantillas ocultas (`{amenity_id}`) y extraer los textos reales de las amenidades activas.
5. **Corregir `reservation_change_history`** (`folio_deep_extract.py:284-291`):
   - Leer las 7 columnas reales de Panel 15: mapear `h_cells[3]` a `event_type`, `h_cells[5]` a `amount` (si es numérico) y unir textos de celdas con espacios (`get_text(" ", strip=True)`) para no pegar palabras (`"status antes de:..."`).
6. **Corregir `channel_phone` y normalizar `"0"`** (`folio_deep_extract.py`):
   - Evitar que el regex de *"Información desde el canal"* capture la siguiente etiqueta cuando un campo viene vacío (usar extracción por nodos `div`/`span` hermanos en lugar de regex sobre texto plano con `|`).
   - Convertir `"0"` literal en `notes`, `channel_reservation_id` y `room_reservation_id` a `None`.
7. **Eliminar duplicación en `services` vs `reservation_night_rates`**:
   - Dejar de insertar filas sintéticas `%-night-%` en `services` (ya existen en `reservation_night_rates`), dejando `services` exclusivamente para los cargos reales del folio.

### Fase C — Rendimiento Sin Redis + API Gateway por Etapas (Fase 1 vs Fase 2)
1. **Eliminar espera de 5s cuando Redis no está activo** (`main.py`, `rate_limiter.py`, `cache.py`):
   - Detectar Redis no disponible con circuit-breaker / timeout corto (`0.5s`) y usar fallback en memoria inmediato.
2. **API Gateway configurable en `.env` (`settings.py` + `main.py`)**:
   - Activar manualmente qué grupos de endpoints se exponen:
     - `API_ENABLE_READ_PUBLIC=true` (Fase 1: consultas de hotel, categorías, habitaciones, disponibilidad, reservas, huéspedes, tarifas, estado, restricciones).
     - `API_ENABLE_INTERNAL_SYNC=true` (endpoints internos de sincronización y salud protegidos).
     - `API_ENABLE_WRITE_ACTIONS=false` (Fase 2: endpoints `POST`/`PATCH`/`DELETE` de interacción con OtelMS).
     - `API_ENABLE_ADMIN_ROUTES=false` (panel `/admin` y CRUDs genéricos).
     - `API_ENABLE_LEGACY_ROUTES=false` (rutas duplicadas o multi-hotel).
3. **Unificar `CalendarSyncService` (legacy) con `SyncService` (principal)**:
   - Deprecar o retirar `CalendarSyncService` una vez que `SyncService` cubra todos los flujos sin errores.
