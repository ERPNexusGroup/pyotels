# Auditoría Integral — OtelMS API no oficial

> **Para Hermes:** Usar `subagent-driven-development` para ejecutar este plan tarea por tarea.

**Goal:** Auditar la plataforma completa (backend + frontend + infraestructura) para identificar deuda técnica, mejoras de seguridad/rendimiento/mantenibilidad, y corregir bugs remanentes.

**Architecture:** FastAPI + SQLAlchemy async + Celery/Redis + Camoufox/Playwright scraping. Frontend SPA admin.html puro (sin framework JS). PostgreSQL en Docker, SQLite en desarrollo local.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0, Celery 5.4, Camoufox 0.5+, Playwright 1.50+, structlog, Pydantic v2, Alembic, Docker Compose (6 servicios)

**Estado actual:** 94 tests passed (77 unit + 17 integration), ruff clean, mypy 0 errores en archivos core (7 pendientes en auth.py), sync funcional en local (calendar 17s, full 35s). Docker `/admin` responde 200 HTML.

---

## Hallazgos de auditoría (severidad ordenada)

### 🔴 Críticos — bugs reales

1. **auth.py `_verify_session` timeout en Docker (45s → 90s fijo)**
   - Causa: `NAVIGATION * 2` no basta; el calendar de OtelMS carga JS pesado y el contenedor tiene 1 CPU limit.
   - Fix real: `wait_until="load"` → `wait_until="networkidle"` con timeout 120s, o detectar `table.calendar_table` con polling en vez de `wait_for_selector`.
   - Archivo: `src/otelms/scraping/auth.py:347-350`

2/router admin — `class Config:` pydantic v1 obsoleto (v2.0 warning, breaks in v3.0)
   - Archivo: `src/otelms/api/routes/admin/config.py:82` — `class Config:` dentro de `HotelResponse`
   - Fix: reemplazar por `model_config = ConfigDict(...)` (ya existe el import en schemas)

### 🟠 Tests — coverage gaps

3. **Test coverage de scraping/auth sin tests unitarios**
   - `src/otelms/scraping/auth.py` tiene 0 tests unitarios directos. Toda la validación depende de integración manual o e2e real.
   - Prioridad: al menos testear el parseo HTTP (httpx mock de `do_single_login` → cookies PHPSESSID + ci_session)
   - Archivo nuevo: `tests/unit/test_auth_http.py`

4. **`_parse_tooltip` duplicado en extractors y parsers**
   - `src/otelms/scraping/extractors/__init__.py:214` y `src/otelms/scraping/parsers/__init__.py:214` tienen la misma función.
   - Extractors está inactivo (0 imports en el pipeline). ¿Dead code o en desarrollo?
   - Acción: si no se usa, quitar `extractors/`. Si es la nueva versión, quitar la de parsers y unificar.

5. **3 TODOs abiertos en sync_service (features pendientes desde inicio)**
   - `services/sync_service.py:574` — extraer servicios del accommodation modal
   - `services/sync_service.py:580` — extraer pagos
   - `dependencies.py:190` — rate limiting
   - Acción: decidir si implementar o mover a issues (backlog visible)

### 🟢 Buenas prácticas — mejoras de mantenibilidad

6. **Celery worker no tiene healthcheck útil**
   - `Dockerfile.worker:46` — el healthcheck hace `redis ping` pero no verifica que Celery esté conectado al broker (se fue a `ready` en log).
   - Fix: `celery -A otelms.tasks.celery_app inspect ping -d celery@$HOSTNAME`

7. **Config vars duplicadas en `pyproject.toml` — dev-deps en dos secciones**
   - `[project.optional-dependencies].dev` vs `[tool.uv].dev-dependencies`
   - Esto genera confusión; uv 0.8+ prioriza `[tool.uv].dev-dependencies` y el otro queda inerte.
   - Acción: consolidar en uno solo (preferencia uv).

8. **`otelms.db` no está en `.gitignore`**
   - `git ls-files | grep otelms.db` devuelve vacío (no tracked), pero `.gitignore` no lo excluye explícitamente — riesgo de commit accidental de credenciales cifradas.
   - Acción: agregar `*.db` al `.gitignore`.

---

## Prioridad de implementación

| # | Tarea | Severidad | Esfuerzo |
|---|---|---|---|
| 1 | `class Config:` → `model_config = ConfigDict` | 🔴 | 5 min |
| 2 | `_verify_session` timeout real (networkidle) | 🔴 | 10 min |
| 3 | Consolidar dev-dependencies + cleanup `[tool.uv]` | 🟢 | 8 min |
| 4 | Eliminar extractors duplicados (si dead code) | 🟡 | 8 min |
| 5 | Tests unitarios de auth HTTP | 🟡 | 15 min |
| 6 | Healthcheck Celery en Dockerfile.worker | 🟢 | 8 min |
| 7 | Agregar `*.db` a .gitignore | 🟢 | 2 min |
| 8 | Decidir/implicar 3 TODOs | 🟡 | 5 min |

---

## Plan paso a paso

### Task 1: Reemplazar `class Config:` por `model_config` en config.py

**Objective:** Eliminar Pydantic v2 deprecation warning

**Files:**
- Modify: `src/otelms/api/routes/admin/config.py:82`

**Step 1: Leer la línea exacta**

```bash
sed -n '80,86p' src/otelms/api/routes/admin/config.py
```

**Step 2: Reemplazar**

```python
# Reemplazar:
    class Config:
        from_attributes = True

# Por:
    model_config = ConfigDict(from_attributes=True)
```

Import de `ConfigDict` en línea 8 del archivo (si no existe).

**Step 3: Verificar — pytest + ruff**

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/ -q
# Expected: 94 passed
env -u PYTHONPATH uvx ruff check src/otelms/api/routes/admin/config.py
# Expected: All checks passed
```

---

### Task 2: Timeout real para `_verify_session`

**Objective:** `networkidle` + timeout 180s para que el calendar JS-heavy no timeoutee en Docker

**Files:**
- Modify: `src/otelms/scraping/auth.py:347-350`

**Step 1: Cambiar patch**

```python
await page.goto(
    self.urls.calendar_url(),
    wait_until="networkidle",       # antes "load"
    timeout=Timeouts.NAVIGATION * 4,  # antes * 2 = 90s → * 4 = 180s
)
```

**Step 2: Verificar en test (sin Playwright real — el test existente no toca esto; el cambio es puntual)**

```bash
cd /d/Coders/...
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/ tests/integration/ -q
# 94 passed
```

**Step 3: Rebuild Docker y probar sync**

```bash
docker compose -f docker/docker-compose.yml build api --no-cache   # background ~7 min
docker compose -f docker/docker-compose.yml up -d api
curl ... # POST /admin/api/sync → success: true
```

### Task 3: Consolidar dev-dependencies

**Objective:** Eliminar duplicación `pyproject.toml` dev deps

**Files:**
- Modify: `pyproject.toml`

**Step 1: Quitar bloque `[tool.uv].dev-dependencies` — dejar solo `[project.optional-dependencies].dev`**

```python
# Pyproject actual:
[tool.uv]
dev-dependencies = [
    "pytest>=8.3.0",
    ...
]

# → eliminar ese bloque (duplicado).
```

El `[project.optional-dependencies].dev` permanece.

**Step 2: Verificar `uv pip install -e ".[dev]"` sigue funcionando**

### Task 4: Eliminar extractors/__init__.py dead code

**Objective:** Quitar ~550 líneas duplicadas

**File to delete/refactor:** `src/otelms/scraping/extractors/__init__.py`

Confirmo 0 imports con:

```bash
grep -rln "extractors" src/ --include="*.py"
```

Si solo tiene el `_parse_tooltip` duplicado y ninguna función importada, eliminarlo.

### Task 5: Test unitario de auth HTTP

Cobertura de `login()` con httpx mock.

### Task 6-8: Mejoras EOS

Agregar healthcheck Celery, `.gitignore` `*.db`, y documentar TODOs.

## Verificación fresca final

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q
# Expected: 94+ passed, 0 failed
ruff check src/
# All checks passed
docker compose up -d api && curl /health && curl /a.admin  # 200 HTML
```