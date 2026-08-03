# Plan de Reorganización del Dashboard Admin — OtelMS API

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Reorganizar la estructura del dashboard admin en 4 módulos principales (Dashboard, CRM, Calendario, Configuración) con sidebar navegable, y completar las funcionalidades de automatización pendientes.

**Architecture:** SPA vanilla JS con sidebar colapsable, 4 módulos independientes. Cada módulo contiene sub-vistas navegables. El backend admin.py actual (~1455 líneas) se refactoriza en submódulos de ruta. Los endpoints de scraping/acciones (cerrar habitación, mover reserva, etc.) ya existen — solo necesitan ser reorganizados en el frontend. El nuevo diseño visual sigue Dark Luxe (#14110f + dorado).

**Tech Stack:** FastAPI + Jinja2 (opcional) o SPA vanilla, PostgreSQL/SQLite, Redis, Chart.js para gráficas.

---

## Plan

### Task 1: Crear estructura de módulos admin en backend

**Objetivo:** Dividir admin.py monolítico (~1455 líneas) en submódulos bajo `admin/` para cada área funcional.

**Files:**
- Crear: `src/otelms/api/routes/admin/__init__.py` (router maestro que importa submódulos)
- Crear: `src/otelms/api/routes/admin/dashboard.py` (stats, sync-logs)
- Crear: `src/otelms/api/routes/admin/crm.py` (close-dates, open-dates, move-reservation, availability, guests, reservations)
- Crear: `src/otelms/api/routes/admin/calendar.py` (calendar view, room status, categories, notifications)
- Crear: `src/otelms/api/routes/admin/config.py` (hotels CRUD, api-keys CRUD, settings)
- Crear: `src/otelms/api/routes/admin/auth.py` (login, jwt, auth middlewares)
- Crear: `src/otelms/api/routes/admin/crud_generic.py` (endpoints genéricos _CRUD_MODELS)
- Renombrar: `src/otelms/api/routes/admin.py` → `src/otelms/api/routes/admin_deprecated.py` (backup temporal)
- Modify: `src/otelmt/api/main.py` → ajustar import de admin

**Verificación:** mypy + ruff en todo `admin/`, verificar que no hay regresiones en endpoints existentes por curl

---

### Task 2: Refactorizar admin.html con sidebar tipo Aceternity/Material

**Objetivo:** Reemplazar el HTML actual (~2261 líneas) con una nueva SPA que tenga sidebar colapsable con 4 módulos.

**Files:**
- Crear: `src/otelms/api/static/admin-v2.html`
- Mantener: `src/otelms/api/static/admin.html` como fallback

**Estructura visual:**
- Sidebar fijo a la izquierda (~64px colapsado, ~260px expandido)
- Iconos para cada módulo: Dashboard, CRM, Calendario, Configuración
- Transición suave colapsar/expandir
- Botón hamburguesa/chevron para togglear
- Logo/nombre del sistema en sidebar expandido

**Diseño Dark Luxe:**
- `--bg: #0f1115`, `--panel: #171a21`, `--border: #2a2d34`
- Acentos en dorado (#c9a96e)
- Usar skill `ui-ux-pro-max` para tokens y `impeccable-frontend` para estándares

**Verificación:**
- HTML carga sin SyntaxError
- Sidebar colapsa/expande
- Navegación entre módulos funciona

---

### Task 3: Implementar módulo Dashboard

**Objetivo:** Centralizar métricas, gráficos y sync logs en un solo módulo.

**Files:**
- Modify: `admin.html` — Sección Dashboard con Chart.js

**Sub-vistas:**
1. **Resumen** — Gráficos de línea/barras con métricas principales (n° hoteles activos, reservas por día, tasa de ocupación)
   - Gráfico 1: Reservas últimas 24h/7d/30d (Chart.js line chart)
   - Gráfico 2: Ocupación por hotel (bar chart comparativo)
   - KPI cards: Total hoteles, sincronizaciones hoy, últimas reservas
2. **Reportes** — Página de informes con filtros de fecha/hotel y exportación CSV
3. **Sync Logs** — Tabla de sync logs con filtros avanzados (ya implementado, solo mover)

**API endpoints:** (ya existen en admin.py):
- `GET /admin/api/stats` — estadísticas generales
- `GET /admin/api/sync-logs` — sync logs

**Verificación:** Gráficos renderizan con datos reales, filtros Sync funcionan

---

### Paso 4: Módulo CRM — Automatización de tareas

**Objetivo:** Concentrar todas acciones operativas sobre el sistema del hotel. Ya existen los endpoints — solo reorganizar UI.

**Archivos:**
- Modify: `admin.html` — Sección CRM con sub-tabs interactivas

**Sub-vistas:**
1. **Cerrar habitaciones** — Form con hotel, fecha desde/hasta, motivo, + preview de habitaciones afectadas
2. **Abrir habitaciones** — Form para desbloquear fechas
3. **Mover reserva** — Seleccionar reserva, nueva habitación, confirmar
4. **Disponibilidad** — Grid con filtros de estado, hotel, fechas
5. **Huéspedes** — Tabla paginada con búsqueda de nombre/documento/email
6. **Precios** — Grid con precio por habitación/por fecha

**API endpoints:** (ya existen)
- `POST /admin/api/tasks/close-dates`
- `POST /admin/api/tasks/open-dates`
- `POST /admin/api/tasks/move-reservation`
- `GET /admin/api/tasks/availability`
- `GET /admin/api/tasks/guests`
- `GET /admin/api/tasks/reservations`

**Verificación:** Cada sub-tab carga datos, formularios, envían POST/GET correctos

---

### Paso 5: Módulo Calendario

**Objetivo:** Vista de tipo calendario para visualizar el estado operativo del hotel por fechas.

**Archivos:**
- New frontend section en admin.html

**Sub-vistas:**
1. **Calendario de reservas** — Vista mensual/semanal con habitaciones en filas, fechas en columnas, bloques de reserva como eventos
2. **Estado de habitaciones** — Grid con círculo de colores indicando estado por día (verde=abierta, roja=bloqueada, amarilla=reservada)
3. **Categorías** — Tabla de categorías con conteo de habitaciones
4. **Notificaciones** — Lista de logs recientes con severidad/iconos

**API endpoints ya existen:**
- `/admin/api/tables/rooms`
- `/admin/api/tables/categories`
- `/admin/api/tables/reservations`

**Verificación:** Calendario renderiza colores correctamente, las categorías están filtrables.

---

### Paso 6: Módulo Configuración

**Objetivo:** Centralizar configuración de hoteles, API Keys y parámetros sistema.

**Archivos:** Sección en admin.html

**Sub-vistas:**
1. **Hoteles** — Tabla con botón editar, eliminar, detalles. Hoteles por ID/nombre/dominio
2. **API Keys** — Formulario CRUD con key mostrada 1 vez al crear, toggle enable/disable
3. **Parámetros generales** — Rate limit, timeouts, headless mode

**API endpoints ya existen:**
- `GET/POST/PUT/DELETE /admin/api/config/hotels`
- `GET/POST/PUT/DELETE /admin/api/config/api-keys`

**Verificación:** Crear, editar, eliminar hoteles y API keys

---

### Paso 7: Tests y verificación final

**Objetivo:** Asegurar que la refactorización no rompe nada.

**Archivos de test:**
- `tests/unit/test_admin_dashboard.py` — nuevos tests para cada submódulo admin
- Los tests existentes deben pasar

**Verificación:**
```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/ -v
# Expected: todos los tests pasen sin regresiones

env -u PYTHONPATH .venv/Scripts/python.exe -m mypy src/otelms/api/routes/admin/
# Expected: 0 errores

env -u PYTHONPATH uvx ruff check src/otelms/api/routes/admin/
# Expected: All checks passed
```

---

## Resumen

| Módulo | Sub-vistas | Endpoints backend | Estado backend |
|--------|-----------|-------------------|----------------|
| Dashboard | Resumen, Reportes, Sync Logs | stats, sync-logs | ✅ Existentes |
| CRM | Cerrar/Abrir, Mover, Disponibilidad, Huéspedes, Precios | tasks/* | ✅ Existentes |
| Calendario | Calendar, Estado Rooms, Categorías, Notificaciones | tables/rooms, categories, reservations | ✅ Existentes |
| Configuración | Hotel, API Keys, Parámetros | config/*, api-keys/* | ✅ Existentes |

**Observación:** Todos los endpoints backend ya existen en `admin.py`. La reorganización es principalmente frontend (HTML + CSS) y extracción de módulos backend admin en archivos separados para mejor mantenibilidad.