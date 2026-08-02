# Admin Dashboard Enhancements Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Extend the admin dashboard with hotel detail view (sub-tables), API Keys CRUD in Config, and a new Tasks tab for date-based operations.

**Architecture:** Extend existing admin.html SPA and admin.py router. Add hotel detail endpoint, API Keys CRUD, and new Tasks tab with date-based operations. Reuse existing modal CRUD infrastructure.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Vanilla JS SPA, SQLite/PostgreSQL, JWT auth.

---

## Current State Analysis

### What Works (Completed Tasks 1-5)
- ✅ Login with API Key → JWT session
- ✅ Dashboard with stats + recent syncs
- ✅ Hotels list with sync buttons
- ✅ Sync Logs with filters
- ✅ Config view (read-only)
- ✅ Tables tab with dynamic grid, search, pagination
- ✅ Modal CRUD (create/edit/delete) with FK dropdowns

### What's Missing (User Requests)
1. **Hoteles tab**: Edit button opens hotel detail with sub-tables (reservas, habitaciones, categorías, huéspedes, pagos, servicios)
2. **Config tab**: API Keys CRUD (currently read-only config display)
3. **Hoteles tab**: Sub-menu for related tables (reservas, habitaciones, categorías, huéspedes, pagos, servicios)
3. **New Tasks tab**: Date-based operations (close dates, open dates, bulk operations)

---

## Plan Overview

### Phase 1: Hotel Detail View & Sub-tables (Hoteles tab)
### Phase 2: API Keys CRUD (Config tab)
### Phase 4: Tasks Tab (Date-based operations)

---

## Phase 1: Hotel Detail View & Sub-tables

### Task 1.1: Add Hotel Detail Endpoint
**Objective:** Create endpoint to get hotel with all related data counts

**Files:**
- Modify: `src/otelms/api/routes/admin.py` (add endpoint)
- Test: `tests/unit/test_admin_crud.py`

**Step 1: Write failing test**
```python
def test_hotel_detail_endpoint():
    # Create hotel, related data
    # GET /admin/api/hotels/{id}/detail
    # Assert counts for all related entities
```

**Step 2: Implement endpoint**
```python
@router.get("/api/hotels/{hotel_id}/detail")
async def hotel_detail(
    hotel_id: str,
    session: AsyncSession = Depends(_get_db),
    _: dict = Depends(_require_admin),
) -> dict:
    # Return hotel + counts of related entities
    # + list of sub-tables with counts
```

**Step 3: Add sub-table navigation in Hotels tab**
- Add "Ver detalle" button in hotels table (replace or add to edit button)
- Click opens detail view with sub-table cards

### Task 1.2: Hotel Detail View (Frontend)
**Objective:** Render hotel detail with sub-table cards

**Files:**
- Modify: `src/otelms/api/static/admin.html` (add `renderHotelDetail` function)

**Step 1: Add renderHotelDetail function**
```javascript
async function renderHotelDetail(hotelId) {
  const data = await api(`/admin/api/hotels/${hotelId}/detail`);
  // Render hotel header + sub-table cards grid
  // Each card: icon, label, count, "Ver" button → navigate to tables tab filtered by hotel
}
```

**Step 2: Add back navigation**
- "← Volver a Hoteles" button

### Task 1.3: Sub-table Navigation
**Objective:** Click "Ver" on sub-table → navigate to Tables tab filtered by hotel

**Files:**
- Modify: `src/otelms/api/static/admin.html` (modify `renderTables` to accept filter params)

---

## Phase 2: API Keys CRUD (Config tab)

### Task 2.1: Add API Keys CRUD Endpoints
**Objective:** Full CRUD for API Keys in admin API

**Files:**
- Modify: `src/otelms/api/routes/admin.py` (add endpoints)
- Test: `tests/unit/test_admin_crud.py`

**Step 1: Write failing tests**
```python
def test_api_keys_list_requires_auth()
def test_create_api_key()
def test_update_api_key()
def test_delete_api_key()
def test_toggle_api_key_active()
```

**Step 2: Implement endpoints**
```python
GET    /admin/api/api-keys              # List with pagination
GET    /admin/api/api-keys/{id}         # Detail
POST   /admin/api/api-keys              # Create (generate key)
PUT    /admin/api/api-keys/{id}         # Update (name, rate_limit, active, expires)
DELETE /admin/api/api-keys/{id}         # Delete
PATCH  /admin/api/api-keys/{id}/toggle  # Toggle active
```

**Special:** POST returns generated key ONCE (like AWS/GitHub)

### Task 2.2: Config Tab - API Keys Section
**Objective:** Replace static config with interactive API Keys management

**Files:**
- Modify: `src/otelms/api/static/admin.html` (modify `renderConfig`)

**Step 1: Split Config tab into sections**
- Tabs within Config: "Configuración" | "API Keys"
- API Keys section: table with CRUD actions

### Task 2.3: API Keys Modal Enhancements
**Objective:** Special handling for API Key creation (show generated key once)

**Files:**
- Modify: `src/otelms/api/static/admin.html` (modal logic)

---

## Phase 3: Tasks Tab (Date-based Operations)

### Task 3.1: Tasks Backend Endpoints
**Objective:** Endpoints for date-based bulk operations

**Files:**
- Modify: `src/otelms/api/routes/admin.py` (new router section)
- Test: `tests/unit/test_admin_crud.py`

**Step 1: Define operations**
```
POST /admin/api/tasks/close-dates      # Close dates for hotel(s)
POST /admin/api/tasks/open-dates       # Open dates for hotel(s)
POST /admin/api/tasks/bulk-sync        # Trigger sync for multiple hotels
GET  /admin/api/tasks/history          # Operation history
```

**Step 2: Implement with Celery tasks**
- Use existing Celery infrastructure
- Return task ID for tracking

### Task 3.2: Tasks Tab Frontend
**Objective:** New tab with date pickers and bulk operations

**Files:**
- Modify: `src/otelms/api/static/admin.html` (add tab, renderTasks function)

**UI Layout:**
```
┌─────────────────────────────────────┐
│ Tareas                              │
├─────────────────────────────────────┤
│ Operación: [Cerrar fechas ▼]        │
│ Hotel: [Todos ▼]                    │
│ Desde: [date]  Hasta: [date]        │
│ [Ejecutar]                          │
├─────────────────────────────────────┤
│ Historial de operaciones            │
│ ┌────┬────────┬────────┬────┬────┐  │
│ │ ID │ Tipo   │ Hotel  │ Fechas    │  │
│ │ 1  │ Cerrar │ Hotel1 │ 1-15 ago  │  │
│ └────┴───────┴────────┴─────┴─────┘  │
└─────────────────────────────────────┘
```

---

## File Summary

### Backend (`src/otelms/api/routes/admin.py`)
| Change | Description |
|--------|-------------|
| + `GET /api/hotels/{id}/detail` | Hotel detail with sub-table counts |
| + `GET/POST/PUT/DELETE /api/api-keys` | API Keys CRUD |
| + `POST /api/api-keys` returns key once | Generate key on create |
| + `PATCH /api/api-keys/{id}/toggle` | Toggle active |
| + `POST /api/tasks/close-dates` | Close dates bulk |
| + `POST /api/tasks/open-dates` | Open dates bulk |
| + `GET /api/tasks/history` | Operation history |

### Frontend (`src/otelms/api/static/admin.html`)
| Change | Description |
|--------|-------------|
| + `renderHotelDetail(hotelId)` | Hotel detail with sub-table cards |
| + `renderConfig()` split into tabs | Config | API Keys |
| + `renderApiKeys()` | API Keys table with CRUD |
| + `renderTasks()` | New Tasks tab |
| + Modal enhancements for API Key create | Show generated key once |
| + Sub-table navigation | "Ver" buttons → Tables tab filtered |

### Tests (`tests/unit/test_admin_crud.py`)
| Test | Description |
|------|-------------|
| `test_hotel_detail_endpoint` | Detail endpoint returns counts |
| `test_api_keys_crud` | Full CRUD flow |
| `test_api_key_create_returns_key_once` | Key shown once |
| `test_tasks_endpoints` | Date operations |

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|------------|
| Modal CRUD already exists but edit buttons say "pendiente" | Verify existing modal works; fix button handlers |
| API Keys creation returns key once | Store temporarily in modal, show in alert |
| Date operations may be long-running | Use Celery async tasks, return task ID |
| Sub-table navigation state | Pass hotel_id via URL hash or state |

---

## Open Questions

1. **Date operations**: What exactly does "cerrar en fechas" / "abrir en fechas" mean? Close/open availability? Block dates?
2. **API Key display**: Show full key in modal alert, or copy-to-clipboard button?
3. **Tasks history**: Store in DB or just Celery result backend?
4. **Hotel detail**: Show counts only, or paginated preview of each sub-table?

---

## Execution Order

1. **Task 1.1-1.3**: Hotel detail + sub-tables (Hoteles tab)
2. **Task 2.1-2.3**: API Keys CRUD (Config tab)
3. **Task 3.1-3.2**: Tasks tab (date operations)

---

*Plan saved to `.hermes/plans/2026-08-02_150000-admin-enhancements.md`*