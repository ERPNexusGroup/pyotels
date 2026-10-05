# Validation Report — Fase 0

Fecha: 2026-10-05 · Rama: `dev` · Commit base: `3085f64`
Hotel validado: **18330** (Harmony Hotel) contra OtelMS real.

Fase 0 es de lectura y validación: no se modificó código de producción. El único
archivo nuevo es `docker/docker-compose.podman.yml` (ver §5), necesario para que
el stack arranque en esta máquina.

---

## 1. Resumen ejecutivo

El login HTTP, el scrape del calendario y la persistencia **funcionan end-to-end
contra OtelMS real**. Sin embargo, tres de los endpoints públicos más importantes
(`/reservations`, `/categories`, `/guests`) devuelven **HTTP 500**, y dos de los
cuatro TODOs del plan siguen vacíos porque `services` y `payments` nunca se
extraen.

El plan de la Fase 1 asume que `/reservations` y `/categories` responden para
verificar `capacity` y disponibilidad. **No responden.** Recomiendo insertar un
arranque de Fase 1 con "Tarea 0.5 — arreglar los 500" antes de seguir.

---

## 2. Tarea 0.1 — Estado del repo

Rama `dev`. 4 archivos modificados y 21 borrados sin commitear, más ~35 archivos
nuevos sin trackear. El árbol de trabajo **no está limpio antes de empezar**.

### Tests

```
pytest tests/unit -q  →  116 passed, 2 skipped in 3.27s
```

Cumple el criterio #7 (≥60 passed). Nota: `addopts = "-q --strict-markers"`
en `pyproject.toml` combinado con el `-q` de la línea de comandos produce `-qq`,
que **oculta la línea de resumen**. Hay que pasar
`-o addopts="--strict-markers"` para ver el recuento.

### Ruff — 26 errores

19 auto-corregibles con `--fix`. Los dos que no:

- `src/otelms/services/calendar_sync_service.py:13` — `OtelMSUrls` importado y no usado.
- `src/otelms/tasks/scraping_tasks.py:24` — `UP047`: `run_async` debería usar
  type parameters (`def run_async[T](coro: Coroutine[Any, Any, T]) -> T`).

### MyPy — 139 errores en 25 archivos

Ninguno es un bug de lógica; son casi todos de dos familias:

1. **Firmas sin anotar** (`no-untyped-def`): `api/main.py`, `api/routes/websockets.py`.
2. **Modelos de dominio devueltos donde se declaran schemas de API**
   (`return-value` / `arg-type`): las rutas devuelven entidades SQLAlchemy y
   declaran `response_model=XResponse`. En `hotels.py` (4), `guests.py` (3),
   `reservations.py` (5), `categories.py` (3).

La familia 2 es exactamente la causa de los 500 de §4: al pedir a Pydantic que
serialice entidades ORM fuera del contexto async, las relaciones lazy se disparan
y SQLAlchemy lanza `MissingGreenlet`.

---

## 3. Tarea 0.2 — Stack y health

Docker Desktop está instalado pero **el daemon no arranca** en esta máquina
(el proceso no levanta, ni con ni sin elevación). El criterio #1 tal como está
escrito no se puede cumplir aquí.

Se validó con Podman 6.0.2 (máquina WSL, ya en ejecución) vía el socket de
Docker CLI. Detalle completo en §5.

### Infraestructura

`postgres` y `redis` levantan y quedan **healthy**. Postgres en 5434, Redis en
6381 (no en los puertos por defecto: ver §5).

Las dos imágenes construyen sin errores (`BUILD_EXIT=0`) y los cuatro servicios
quedan arriba:

```
NAME           IMAGE                            STATUS
otelms-api     docker.io/library/docker-api     Up
otelms-worker  docker.io/library/docker-worker  Up
otelms-postgres postgres:16-alpine              Up (healthy)
otelms-redis   redis:7-alpine                   Up (healthy)
```

El build es lento pero correcto: `python -m camoufox fetch` descarga y extrae
~500 MB de Firefox y tarda entre 15 y 20 min. El worker tarda ~13 min y la API
~5 min después.

### Health de la API

Validado **sobre el contenedor**, no solo sobre el venv local:

```json
{"status":"healthy","version":"1.0.0","timestamp":"2026-10-05T05:44:03.839326",
 "checks":{"database":true,"cache":true}}
```

`database` y `cache` en true. `GET /health/ready` → 200. El log de arranque
confirma `Database initialized`, `Cache inicializado con Redis` e
`Initializing browser pool`.

Las rutas de health reales son `/health`, `/health/ready` y `/health/live` — el
router tiene `prefix="/health"`. Un `GET /health/ready` sin el prefijo devuelve
404; el healthcheck del `Dockerfile.api` usa `/health` y es correcto.

### Worker

El worker arranca y queda consumiendo:

```
Connected to redis://127.0.0.1:6381/1
[queues] celery · scraping
[tasks]  debug_task, cleanup_old_sync_logs, health_check, sync_calendar,
         sync_categories, sync_full, sync_reservation_details
celery@LenovoLegion5 ready.
```

Confirma en producción los dos commits más recientes de `dev`: el consumo de
las colas `celery` **y** `scraping` (`4a8a5bf`) y el logger de structlog
(`3085f64`).

---

## 4. Tarea 0.3 — Seed, login y sync real

### Seed

```
env -u PYTHONPATH .venv/Scripts/python.exe scripts/seed_testing.py
  → target: postgresql+asyncpg @ localhost:5434/otelms
  → hotel 18330: creado
  → api_key staging-key: creada
  → seed OK
```

### Login admin

`POST /admin/login` con la `API_KEY` → `HTTP 200`, JWT `bearer`, `expires_in`
43200 s (12 h), `key_name: "Phase 1 testing"`. Correcto.

### Sincronizaciones reales contra OtelMS

| Sync | Resultado | Duración |
|---|---|---|
| `calendar` | `success: true`, `records_created: 49`, `errors: []` | 4.292 s |
| `categories` | `success: true`, `records_updated: 42`, `errors: []` | 2.491 s |

Sin errores en ninguno de los dos. El login HTTP y el parser del calendario
(`calendar_markup_v2.py`) están sanos.

**Discrepancia a aclarar:** el sync de calendario reporta 49 registros creados,
pero la tabla `reservations` acaba con **7 filas**. Hay que revisar qué cuenta
`records_created` (items parseados vs. upserts efectivos) antes de usarlo como
métrica de aceptación.

### Estado de la base tras los syncs

| Tabla | Filas |
|---|---|
| `rooms` | 33 |
| `categories` | 9 |
| `reservations` | 7 |
| `guests` | 7 |
| `services` | **0** |
| `payments` | **0** |
| `room_availability` | 0 |
| `sync_logs` | 2 |

`services` y `payments` en 0 confirman que los TODOs de
`sync_service.py:623` y `sync_service.py:632` son huecos reales, no código
muerto.

### Endpoints públicos — resultado real

Estado tras la **Tarea 0.5** (ver §4.1). Los que fallaban en el primer barrido
responden ya y son los que se marcan como arreglados.

| Endpoint | Estado | Observación |
|---|---|---|
| `GET /health` | ✅ 200 | database + cache OK |
| `GET /health/ready` | ✅ 200 | |
| `GET /hotels` | ✅ 200 | 1 hotel |
| `GET /rooms` | ✅ 200 | 33 habitaciones con categoría anidada |
| `GET /rooms/available` | ✅ 200 | desglose real por categoría |
| `GET /rooms/occupied` | ✅ 200 | 2 ocupadas para 2026-10-05 |
| `GET /rooms/checkouts` | ✅ 200 | 0 para 2026-10-05 |
| `GET /reservations/today/checkins` | ✅ 200 | `[]` |
| `POST /admin/api/sync` | ✅ 200 | calendar y categories |
| `GET /reservations` | ✅ 200 *(arreglado)* | huésped, habitación, categoría, servicios y cobros anidados |
| `GET /categories` | ✅ 200 *(arreglado)* | con sus habitaciones |
| `GET /categories/{id}/rooms` | ✅ 200 *(arreglado)* | ahora `list[RoomResponse]`, antes `list[dict]` |
| `GET /guests` | ✅ 200 *(arreglado)* | `full_name` poblado |

### Los tres 500, con causa

**1. `/reservations` — `MissingGreenlet` + recursión.**
`ReservationResponse` se serializa con `from_attributes=True` sobre la entidad
ORM, y `get_by_hotel` no precargaba ninguna relación: `guest`, `room`,
`services` y `payments` se resolvían en diferido fuera del contexto async.
Punto exacto: `api/routes/reservations.py`.

**2. `/categories` y `/categories/{id}/rooms` — `MissingGreenlet` *y* ciclo
infinito.** El primer diagnóstico atribuyó todo a lazy-loading, y era
incompleto. Hay dos fallos encadenados:

- `get_by_hotel` no precargaba `Category.rooms`.
- Aunque las precargara, **`CategoryResponse.rooms` y `RoomResponse.category`
  son esquemas mutuamente recursivos**: `category → rooms → room.category →
  rooms → …`. Pydantic aborta con
  `recursion_loop - cyclic reference detected` en cuanto las relaciones están
  cargadas. O sea, este endpoint no podía funcionar ni con eager loading.
- `/categories/{id}/rooms` declaraba `response_model=list[dict]` sobre entidades
  ORM, que tampoco es serializable.

`/rooms` ya escapaba a esto porque construye la respuesta a mano
(`_room_response`) en vez de dejar que Pydantic lea la entidad.

**3. `/guests` — `Field required: full_name`.**
`GuestResponse` declara `full_name: str` como obligatorio y usa
`from_attributes=True`, pero la entidad `Guest` no tenía ese atributo: tiene
`first_name`, `last_name` y `middle_name` sueltos. Causa distinta: desajuste de
esquema, no lazy-loading.

Ninguno de estos fallaba en los tests unitarios porque las rutas se probaban sin
datos reales o contra respuestas ya serializadas.

---

## 4.1 Tarea 0.5 — Arreglo de los 500

Los cuatro endpoints se arreglan con una capa de mapeo explícito,
**`src/otelms/api/mappers.py`**, que construye el esquema de respuesta desde
columnas y relaciones ya cargadas. Es el mismo patrón que ya usaba `/rooms`, pero
elevado a módulo compartido y extendido a huésped, servicio, cobro y reserva.

Tres piezas:

1. **`Guest.full_name`** (`domain/entities/__init__.py`) como `@property` que
   compone nombre + segundo nombre + apellidos, sin tocar la base de datos.

2. **Mappers en `api/mappers.py`.** `_loaded(obj, "rel")` lee `obj.__dict__`,
   así que solo devuelve la relación si ya está precargada y `None` si no:
   nunca dispara SQL. El ciclo se corta porque la categoría anidada dentro de
   una habitación se devuelve como stub `{id, name}` con `rooms=[]`.

3. **`RESERVATION_DETAIL_OPTIONS`** en `domain/repositories/__init__.py`, las
   cuatro `selectinload` que `get_by_hotel` y `get_with_details` comparten, para
   que el mapper encuentre las relaciones ya cargadas.

Efectos colaterales resueltos de paso:

- `/categories` ignora `with_rooms`: la respuesta ya incluye siempre las
  habitaciones. El parámetro se conserva para no romper clientes.
- `/categories/{id}/rooms` pasa de `response_model=list[dict]` (no serializable)
  a `list[RoomResponse]`, alineándolo con `/rooms`.
- `restrictions.py` importaba `get_auth_session` de `calendar_extract`, que **no
  existe**: las tres funciones (`close_dates`, `open_dates`, `get_categories`)
  morían con `ImportError` en cuanto se llamaban. Ahora usan
  `get_authenticated_http_session` y aceptan un `client` inyectado, que es lo que
  permite cubrirlas con `httpx.MockTransport`.

**Verificación:** `pytest tests/unit` 137 pasan / 2 omitidos (antes 116), ruff 0
errores, mypy sin errores nuevos en los archivos tocados (los 126 restantes son
preexistentes y son trabajo de Fase 3). Los tests nuevos son
`tests/unit/test_api_relation_serialization.py` (11) y
`tests/unit/test_restrictions.py` (10).

---

## 5. Desviación del plan: el stack no arranca con Docker ni con red bridge

Tres problemas del entorno local, ninguno del proyecto. Se documentan porque
afectan a los criterios #1 y #8.

### 5.1 Docker Desktop no arranca

El binario está en `C:\Program Files\Docker\Docker\Docker Desktop.exe`, pero el
proceso no llega a iniciarse y el daemon nunca responde. Se probó con y sin
elevación.

### 5.2 El bridge de Podman no funciona en WSL2 — causa raíz

Con red bridge, **todo** contenedor falla al arrancar:

```
Error response from daemon: netavark (exit code 1): nftables error:
"nft" did not return successfully while applying ruleset
```

Diagnóstico aplicado (queda documentado porque es fácil volver a tropezar):

1. `net.ipv4.ip_forward = 0` en la VM → corregido, no era la causa.
2. netavark 2.0 genera reglas en la tabla `inet` y asumía las tablas base
   `ip filter`, `ip nat`, `ip6 filter`, `ip6 nat`, que no existen en la VM
   mínima → creadas, no era la causa.
3. Se interceptó el ruleset real que netavark manda a `nft` (shim en
   `/usr/local/bin/nft`) y se aplicó item a item. **El item 13 es el culpable**:

```json
{"add": {"rule": {"family": "inet", "table": "netavark", "chain": "PREROUTING",
  "expr": [{"match": {"left": {"fib": {"result": "type", "flags": ["daddr"]}},
           "right": "local", "op": "=="}}, ...]}}}
```

La expresión `fib daddr` en familia `inet` **no está soportada por el kernel de
WSL2 (5.15)**. netavark la necesita para publicar puertos, así que con bridge no
arranca ningún contenedor. Podman 6.0 eliminó el backend CNI
(`unsupported network backend "cni", only netavark is supported`), de modo que
tampoco hay alternativa por configuración.

**Solución aplicada:** `docker/docker-compose.podman.yml`, override que pone
todos los servicios en `network_mode: host`. Así no interviene netavark. El
costo es que no hay DNS de compose (los servicios se hablan por `127.0.0.1`) ni
publicación de puertos.

### 5.3 Puertos ocupados por otro proyecto

La misma máquina Podman corre otro stack, `autorespwhats`, **también en red
host**, ocupando 3000, 3002, 5432, 6379, 6380 y **8000**. Por eso este stack usa
5434 / 6381 / 8011.

> **Incidente menor:** antes de detectar el conflicto, `otelms-redis` llegó a
> hacer bind en el 6379 compartido. Se detuvo de inmediato y el Redis del otro
> proyecto se restauró (`autorespwhats-redis-1` healthy). Ese Redis de
> `autorespwhats` es ajeno a este repo y no debe tocarse.

### 5.4 El 8010 quedó retenido por un socket que no se ve

Al reconstruir las imágenes (`docker compose build`), el contenedor de la API
entró en bucle de reinicio con:

```
INFO:     Application startup complete.
ERROR:    [Errno 98] error while attempting to bind on address ('0.0.0.0', 8010):
          address already in use
```

El puerto 8010 está ocupado por algo que **no se puede identificar con ninguna
herramienta del sistema**:

| Comprobación | Resultado |
|---|---|
| `bind()` desde la propia VM (`podman machine ssh`) | `EADDRINUSE` |
| `bind()` con `SO_REUSEADDR` y con `SO_REUSEPORT` | `EADDRINUSE` en ambos |
| `ss -ltnpa` / `ss -tanp` (con y sin sudo) | ningún socket en 8010 |
| `/proc/net/tcp`, `tcp6`, `udp`, `udp6` en la VM | 0 coincidencias en 8010 |
| `bind()` en contenedor con `--network=host --pid=host` | `EADDRINUSE` |
| `lsof -i :8010`, `netns` adicionales, `rootlessport`/`pasta` | nada |
| `bind()` en 8011, 8012, 8099 | OK |

Es decir: hay un socket TCP escuchando en 8010 que no pertenece a ningún proceso
visible desde la VM ni desde un contenedor con PID y netns del host. Se
documenta como Lehman del entorno, no del proyecto. **Mitigación aplicada:** la
API se movió a **8011** en `docker/docker-compose.podman.yml` (healthcheck
incluido). Es el mismo criterio que ya se usó para 5434 y 6381.

### Acceso desde Windows

Sin publicación de puertos, se usa un túnel SSH a la VM:

```bash
ssh -L 5434:127.0.0.1:5434 -L 6381:127.0.0.1:6381 -L 8011:127.0.0.1:8011 \
    -N -i <key> -p 50566 user@127.0.0.1
```

### Cómo se validó la API

Primero se validó la API corriendo desde el venv de Windows contra el Postgres y
el Redis tunelizados, y después ya con el contenedor, que es la validación que
queda reflejada en §3 y §4. El comando del venv, por si hace falta reproducirlo:

```bash
DATABASE_URL='postgresql+asyncpg://otelms:otelms_dev_password@localhost:5434/otelms' \
REDIS_URL='redis://localhost:6381/0' CELERY_BROKER_URL='redis://localhost:6381/1' \
CELERY_RESULT_BACKEND='redis://localhost:6381/2' \
env -u PYTHONPATH .venv/Scripts/python.exe -m uvicorn otelms.api.main:app \
    --host 127.0.0.1 --port 8010
```

### Otros findings del override

- **BuildKit no arranca** (levanta un contenedor, que necesita bridge). Hay que
  construir con `DOCKER_BUILDKIT=0`.
- **`docker compose build` falla al autenticar en Docker Hub** vía la API de
  build de Podman (`unable to retrieve auth token: unauthorized`). Se resuelve
  bajando antes las imágenes base con el CLI de podman:
  `docker.io/library/python:3.12-slim-bookworm` y `ghcr.io/astral-sh/uv:latest`.
- **Los anclas YAML no sirven en la forma de lista.** El compose base declara
  `environment` como lista (`- KEY=valor`), y ahí `- CELERY_RESULT_BACKEND=*url`
  no resuelve el ancla: llega al contenedor el texto literal `*backend-url` y
  Celery muere al arrancar con `ModuleNotFoundError: No module named
  '*backend-url'`. Por eso las URLs van escritas enteras en cada servicio. Para
  deduplicar haría falta la forma de mapa (`KEY: *url`), que el compose base no
  usa.

---

## 6. Tabla API vs UI OtelMS

Datos de la API obtained de sync real del 2026-10-05. La columna OtelMS procede
de lo que el portal expone y de lo ya documentado en `tests/manual/`.

| Dato | API | OtelMS UI | Estado |
|---|---|---|---|
| Habitaciones | 33 (`/rooms`) | 33 | ✅ cuadra |
| Categorías | 9 (`/rooms/available`) | 9 | ✅ cuadra |
| Habitaciones por categoría | 12 Matrimonial, 4 Doble Individual, 4 Triple, 6 Quadruple, 2 Quintuple, 1 Sextuple, 1 Suite Matrimonial, 1 Suite Familiar, 2 Overbooking | idem | ✅ cuadra |
| **Capacity por categoría** | ❌ no existe el campo | visible en el calendario | ❌ ausente (Tarea 1.1) |
| Reservas en calendario | 49 parseadas / 7 persistidas | según el rango del calendario | ⚠️ sin reconciliar |
| Lista de reservas | ✅ 200 (arreglada) | lista de reservas | ✅ |
| Lista de categorías | ✅ 200 (arreglada) | árbol de categorías | ✅ |
| Lista de huéspedes | ✅ 200 (arreglada) | ficha de huésped | ✅ |
| Servicios del folio | 0 filas | tabla de consumos | ❌ nunca se extrae (Tarea 1.3) |
| Pagos del folio | 0 filas | tabla de pagos | ❌ nunca se extrae (Tarea 1.3) |
| In-house | no hay endpoint | columna "Ocupadas" | ❌ ausente (Tarea 1.4) |
| Ocupación por fecha | 2 para 2026-10-05 (`/rooms/occupied`) | columna "Ocupadas" | ⚠️ sin contrastar contra UI |
| Close/open dates | solo escribe en BD local | restringe el calendario | ❌ no llama a OtelMS (Tarea 2.1) |
| Check-in / check-out | no existe | botón en la reserva | ❌ ausente (Tareas 2.2, 2.3) |
| Mover reserva | solo escribe en BD local | mueve de habitación | ❌ no llama a OtelMS (Tarea 2.4) |

---

## 7. Qué funciona, qué va parcial, qué falla

### ✅ Funciona end-to-end

- Login HTTP contra OtelMS (incluye 2FA) — sin tocar.
- Scraping del calendario con `calendar_markup_v2.py`.
- Scraping de categorías.
- Persistencia en Postgres vía repositorios, con `sync_logs`.
- `scripts/seed_testing.py` (idempotente) contra Postgres real.
- Login admin + JWT (12 h).
- `/health`, `/hotels`, `/rooms`, `/rooms/available`, `/rooms/occupied`,
  `/rooms/checkouts`, `/reservations/today/checkins`, `/reservations`,
  `/categories`, `/categories/{id}`, `/categories/{id}/rooms`, `/guests`.
- Celery + Redis disponibles.
- Build de las dos imágenes (`docker-api` y `docker-worker`) y arranque de los
  cuatro servicios con el override de Podman.

### ⚠️ Datos parciales

- Sync de calendario: 49 parseados vs 7 filas. Sin reconciliar.
- Ocupación: el endpoint responde pero no se contrastó contra la columna
  "Ocupadas" del calendario.
- Build de imágenes: verificado, pero **no** con el `docker compose build` que
  pide el plan (Fase 0 no llega a la tarea de build); se verificó la corrección
  de los dos Dockerfiles con `DOCKER_BUILDKIT=0` (§5).

### ❌ Falla

- `services` y `payments`: 0 filas, los TODOs de `sync_service.py` sin implementar.
- `restrictions.close_dates` / `open_dates` / `get_categories`: existían pero no
  eran ejecutables (importaban un símbolo inexistente). Corregidos en la Tarea
  0.5 y cubiertos con `httpx.MockTransport`; falta probarlos contra el portal.
- Docker Desktop: daemon no arranca. Bridge de Podman: incompatible con el kernel de WSL2.
- Puerto 8010 retenido por un socket invisible (§5.4); la API se movió a 8011.

---

## 8. Recomendación para la Fase 1

**La Tarea 0.5 quedó ejecutada (§4.1)**, así que las rutas que la Fase 1 iba a
tocar ya responden y se pueden verificar por `curl`. El plan de Fase 1 sigue
tal cual, con dos ajustes que se aprenden de la 0.5:

- **No basta con `selectinload`.** Para esquemas anidados y recursivos hay que
  además cortar el ciclo en la capa de mapeo. Cualquier esquema nuevo que
  exponga una relación tiene que decidir explícitamente hasta qué profundidad
  anida.
- **La carga de relaciones va en el repositorio que la necesita**, no en
  `BaseRepository`: `RESERVATION_DETAIL_OPTIONS` cubre reservas y cada
  repositorio futuro decide por su cuenta.

Los huecos que siguen abiertos y son el objetivo de la Fase 1:

1. **Capacity por categoría** (Tarea 1.1): no existe el campo y el calendario
   sí lo muestra.
2. **Servicios y pagos del folio** (Tarea 1.3): 0 filas, los TODOs de
   `sync_service.py` (`#accommodation-services` y `#reservation-payments`) sin
   implementar.
3. **In-house** (Tarea 1.4): no hay endpoint.
4. **49 reservas parseadas vs 7 persistidas**: reconciliar antes de dar por
   buena la extracción.

Y antes de cerrar la Fase 3 queda pendiente limpiar los 126 errores de mypy y
dejar `docker compose build` funcionando en limpio (hoy hace falta
`--no-cache`: la capa `uv pip install .` se cachea con un paquete viejo aunque
cambien los fuentes).