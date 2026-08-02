# Django-Like Admin CRUD Implementation Plan

> **For Hermes:** Use `subagent-driven-development` skill to implement this plan task-by-task.

**Goal:** Expand the admin dashboard to view, edit, create, and delete data from all key database tables (`hotels`, `categories`, `rooms`, `reservations`, `guests`, `api_keys`), providing a generic, dynamic CRUD interface similar to Django Admin.

**Architecture:**
- **Dynamic Backend CRUD Router:** Create a single set of generic REST endpoints inside `api/routes/admin.py` that map dynamically to SQLAlchemy models. This avoids duplicating code for each table and guarantees strict schema validation.
- **Dynamic Frontend UI:** Expand `api/static/admin.html` with a new "Tables" view. This view renders table grids dynamically, handles foreign key drop-downs, and auto-generates forms (input, select, checkbox, datetime picker) based on column definitions.
- **Strict Debug Guard:** All CRUD endpoints require the admin JWT session token and are only active when `settings.app_debug` is True.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Python-Jose (JWT), SQLite, Vanilla JS SPA (HTML5/CSS3).

---

## Technical Mapping

The generic endpoint will map table slugs to their SQLAlchemy models:

```python
_CRUD_MODELS = {
    "hotels": Hotel,
    "categories": Category,
    "rooms": Room,
    "reservations": Reservation,
    "guests": Guest,
    "api-keys": ApiKey,
}
```

Foreign Key mappings for dynamic UI selects:
- `hotel_id` -> lists available `Hotel` records (`id` and `name`)
- `category_id` -> lists available `Category` records (`id` and `name`)
- `room_id` -> lists available `Room` records (`id` and `name`)
- `guest_id` -> lists available `Guest` records (`id`, `first_name` + `last_name`)

---

## Detailed Step-by-Step Plan

### Task 1: Create generic backend schemas and mappings

**Objective:** Add helper schemas for dynamic tabular listings, row updates, and metadata.

**Files:**
- Modify: `src/otelms/api/routes/admin.py`

**Step 1: Write failing test**
Create a unit test targeting the future dynamic schema mapping:
```python
# Create: tests/unit/test_admin_crud.py
import pytest
from otelms.api.routes.admin import _CRUD_MODELS

def test_crud_models_mapping():
    assert "hotels" in _CRUD_MODELS
    assert "api-keys" in _CRUD_MODELS
```

**Step 2: Run test to verify failure**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: FAIL (Module import error or `_CRUD_MODELS` not found)

**Step 3: Write minimal implementation**
Declare `_CRUD_MODELS` inside `src/otelms/api/routes/admin.py` and declare schemas for dynamic updates:
```python
# src/otelms/api/routes/admin.py
from pydantic import BaseModel
from typing import Any

class RowUpdatePayload(BaseModel):
    data: dict[str, Any]
```

**Step 4: Run test to verify pass**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: PASS

**Step 5: Commit**
```bash
git add src/otelms/api/routes/admin.py tests/unit/test_admin_crud.py
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin): add dynamic CRUD models map and payload schema"
```

---

### Task 2: Implement dynamic Listing and Detail retrieval endpoints

**Objective:** Add `GET /admin/api/tables/{table_slug}` and `GET /admin/api/tables/{table_slug}/{id}` endpoints.

**Files:**
- Modify: `src/otelms/api/routes/admin.py`

**Step 1: Write failing test**
Verify listing a dynamic table returns the rows:
```python
# tests/unit/test_admin_crud.py
@pytest.mark.asyncio
async def test_get_table_rows_unauthorized(client):
    response = client.get("/admin/api/tables/hotels")
    assert response.status_code == 401
```

**Step 2: Run test to verify failure**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: FAIL (404 Not Found)

**Step 3: Write minimal implementation**
Implement dynamic retrieval inside `admin.py`:
```python
# src/otelms/api/routes/admin.py
@router.get("/api/tables/{table_slug}")
async def list_table_rows(
    table_slug: str,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(_get_db),
    _: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    if table_slug not in _CRUD_MODELS:
        raise HTTPException(status_code=404, detail="Table not mapped")
    model = _CRUD_MODELS[table_slug]
    
    # Dynamic select
    stmt = select(model).offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    
    # Serialize to dict of attributes
    serialized = []
    for row in rows:
        serialized.append({c.name: getattr(row, c.name) for c in model.__table__.columns})
        
    return {
        "columns": [c.name for c in model.__table__.columns],
        "rows": serialized
    }
```
Add another endpoint for `GET /api/tables/{table_slug}/{id}` in the exact same manner.

**Step 4: Run test to verify pass**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: PASS

**Step 5: Commit**
```bash
git add src/otelms/api/routes/admin.py tests/unit/test_admin_crud.py
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin): implement dynamic listing and detail endpoints"
```

---

### Task 3: Implement dynamic Update, Create, and Delete endpoints

**Objective:** Add `PUT`, `POST`, and `DELETE` endpoints for the dynamic CRUD system.

**Files:**
- Modify: `src/otelms/api/routes/admin.py`

**Step 1: Write failing test**
Create a test to check dynamic deletion of a Category or Room:
```python
# tests/unit/test_admin_crud.py
@pytest.mark.asyncio
async def test_delete_row_requires_auth(client):
    response = client.delete("/admin/api/tables/categories/some-id")
    assert response.status_code == 401
```

**Step 2: Run test to verify failure**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: FAIL (404 Not Found)

**Step 3: Write minimal implementation**
Implement endpoints inside `admin.py`:
- `POST /api/tables/{table_slug}`: Instantiates model with `**payload.data`, adds to session, commits.
- `PUT /api/tables/{table_slug}/{id}`: Retrieves model, updates matching attributes from `payload.data`, commits.
- `DELETE /api/tables/{table_slug}/{id}`: Retrieves model, deletes from session, commits.

*Ensure handling of special types like `datetime` strings (parse using `datetime.fromisoformat` if the SQLAlchemy column is a DateTime column).*

```python
# Parse types dynamically helper
def _cast_payload_values(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    casted = {}
    for col in model.__table__.columns:
        if col.name in data and data[col.name] is not None:
            val = data[col.name]
            if isinstance(col.type, DateTime) and isinstance(val, str):
                casted[col.name] = datetime.fromisoformat(val.replace("Z", "+00:00"))
            elif isinstance(col.type, Numeric) and val != "":
                casted[col.name] = Decimal(str(val))
            else:
                casted[col.name] = val
    return casted
```

**Step 4: Run test to verify pass**
Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py`
Expected: PASS

**Step 5: Commit**
```bash
git add src/otelms/api/routes/admin.py tests/unit/test_admin_crud.py
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin): implement update, create, and delete dynamic operations"
```

---

### Task 4: Expand Frontend UI layout for Django-like Tables tab

**Objective:** Add a new tab "Tablas" in the sidebar of `admin.html` with a dropdown to select which table to view.

**Files:**
- Modify: `src/otelms/api/static/admin.html`

**Step 1: Write static structure**
Inject the sidebar button and a placeholder panel:
```html
<button data-view="tables">🗂️ Django Admin Tables</button>
```

**Step 2: Add CSS layout for tables**
Ensure standard Django Admin aesthetic inside `admin.html` (light-bordered tables, green headers or clean dark panel style, explicit add buttons, clean actions).

**Step 3: Run local static check**
Open `http://127.0.0.1:8010/admin` in the browser or via curl to confirm the sidebar tab renders correctly.

**Step 4: Commit**
```bash
git add src/otelms/api/static/admin.html
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin-ui): add Tables navigation item and visual container"
```

---

### Task 5: Implement dynamic Table Grid and Search

**Objective:** Write the JS client-side script to pull columns/rows from `/admin/api/tables/{table_slug}` and display them dynamically.

**Files:**
- Modify: `src/otelms/api/static/admin.html`

**Step 1: Implement table renderer**
Write `renderTablesView()` in JS to fetch columns and rows.
```javascript
async function renderTablesView(tableSlug = "hotels") {
  const c = $("#content");
  // Render sub-navigation for selecting tables
  // Fetch table data from /admin/api/tables/${tableSlug}
  // Generate <table> dynamically using data.columns as <th> and data.rows as <td>
}
```

**Step 2: Implement search filtering**
Add a text filter box on top. Filter rows client-side or pass a search query to the backend.

**Step 3: Verify**
Refresh `/admin` page and check that you can toggle between "Hoteles", "Categorías", "Habitaciones" and view real database records correctly.

**Step 4: Commit**
```bash
git add src/otelms/api/static/admin.html
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin-ui): implement dynamic grid generation and table filtering"
```

---

### Task 6: Implement dynamic Edit/Create Modal with form validation

**Objective:** Build a dynamic popup form that detects column types (text, checkbox for booleans, date inputs) and generates the correct fields.

**Files:**
- Modify: `src/otelms/api/static/admin.html`

**Step 1: Add modal markup**
Inject a hidden `<div class="modal" id="crudModal">` with a dynamic form container inside `admin.html`.

**Step 2: Write modal builder JS**
```javascript
function openCrudModal(tableSlug, rowData = null) {
  // If rowData is null -> Create mode. Else -> Edit mode.
  // For each column in table metadata, append an input element:
  // - boolean -> <input type="checkbox">
  // - datetime -> <input type="datetime-local">
  // - foreign key -> <select> loaded from relational data
  // - others -> <input type="text">
}
```

**Step 3: Bind PUT/POST requests**
On form submission, gather input values and send `POST /admin/api/tables/{tableSlug}` (Create) or `PUT /admin/api/tables/{tableSlug}/{id}` (Edit). Reload the active grid on success.

**Step 4: Verify**
Validate by editing a Hotel's metadata (e.g. rate limit or description) or adding a Category. Confirm that edits are committed to `otelms.db` instantly.

**Step 5: Commit**
```bash
git add src/otelms/api/static/admin.html
git -c user.name="Walter Cun" -c user.email="walte@local" commit -m "feat(admin-ui): implement dynamic CRUD modal and form submission"
```

---

## Verification & Integrity Check

After all tasks are completed:
1. Run the entire backend test suite:
   `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/`
   Expected: 100% green.
2. Run Mypy to guarantee zero type regressions:
   `env -u PYTHONPATH .venv/Scripts/python.exe -m mypy src/otelms`
   Expected: "Success: no issues found".
3. Run Ruff for style compliance:
   `env -u PYTHONPATH uvx ruff check src/otelms`
   Expected: Clean linter run.
4. Final rebuild of Docker images to check production builds:
   `docker compose -f docker/docker-compose.yml build`

---

## Risks, Tradeoffs, and Open Questions

- **Cascade Deletes:** Deleting rows dynamically (e.g. a Hotel) triggers cascade deletes on Categories, Rooms, and Reservations. A modal confirmation with warnings is implemented to mitigate accidental deletion risks.
- **Relational Dropdowns Performance:** Loading all relational options into `<select>` dropdowns (e.g. selecting a Guest for a Reservation) is lightweight for typical local multi-hotel scales. If database sizes grow exponentially, the plan can be optimized in the future with paginated async search dropdowns.
