# Deuda Técnica OtelMS — Plan de Reparación

> **Fecha:** 2026-08-01 · **Autor:** Hermes (con Walter)
> **Ejecución:** directa tarea por tarea (autorizada: "arma el plan y ejecuta")

**Goal:** Dejar el repo con 0 tests fallando, 0 errores ruff y mypy limpio (o config calibrada y honesta), manteniendo el stack Docker healthy.

**Contexto actual (baseline verificado 2026-08-01):**
- pytest: **22 passed + 2 skipped + 8 failed** — los 8 fallos son bugs REALES del código (no tests rotos)
- ruff: **606 errores** — 149 UP045, 102 W293, 91 PLC0415, 42 I001, 37 W292, 24 TRY003, 24 PLR091, 23 TRY400, 22 UP006, 18 TRY300, 13 UP035, 12 UP017, **8 F821 (undefined name = bugs potenciales)**, 7 ERA001, 7 E712, resto menor
- mypy: **263 errores** — 58 no-untyped-def, 43 attr-defined, 36 assignment, 23 union-attr, 22 arg-type, 14 return-value, 11 no-any-return, 8 var-annotated, **8 name-defined**, 8 dict-item, 7 call-overload, 6 valid-type, 5 import-untyped, resto menor

---

## FASE A: 8 tests fallando (bugs reales, TDD — RED ya confirmado)

### Task A1: Parsers — no incluir `fields` vacío + resolver `guest_name` faltante
**Causa raíz:**
- `ReservationDetailParser.parse_basic_info` y `ModalParser.parse` siempre agregan `data["fields"] = fields_map` → HTML vacío devuelve `{'fields': {}}` ≠ `{}`
- El lookup de campos usa `label.find_parent("div").find_next_sibling("div", class_="text-right")` → con el HTML plano del test (`<span class="incolor">` + `<div class="text-right">` como hermanos directos en el panel) no encuentra nada → falta `guest_name`

**Fix:**
1. Solo setear `data["fields"]` si `fields_map` tiene contenido
2. Cambiar el lookup a `label.find_next("div", class_="text-right")` (funciona con y sin wrapper)

**Files:** `src/otelms/scraping/parsers/__init__.py` (líneas ~287, ~484, ~273-286, ~470-483)
**Tests:** `tests/unit/test_parsers.py::TestReservationDetailParser::{test_parse_basic_info_empty, test_parse_basic_info_with_data}`, `TestModalParser::{test_parse_empty, test_parse_with_data}`

### Task A2: GuestRepository.get_or_create_by_name — generar id
**Causa raíz:** `Guest.id` es PK String(64) sin default; `get_or_create_by_name` crea Guest sin id → `NOT NULL constraint failed: guests.id`
**Fix:** generar `guest_id = f"guest_{hash(name)}"` (mismo patrón que `upsert_from_scraper`, línea ~317) antes de crear; usar `hashlib.sha256(name.encode()).hexdigest()[:12]` para determinismo estable entre procesos.
**Files:** `src/otelms/domain/repositories/__init__.py` (~línea 297)
**Tests:** `tests/unit/test_repositories.py::TestGuestRepository::test_get_or_create_by_name`

### Task A3: ReservationRepository.upsert_from_scraper — import datetime faltante
**Causa raíz:** `NameError: name 'datetime' is not defined` en línea 486 — la función usa `datetime.now(timezone.utc)` sin import local (los imports `datetime` están en otras funciones).
**Fix:** agregar `from datetime import datetime, timezone` al inicio de la función.
**Files:** `src/otelms/domain/repositories/__init__.py` (línea ~452)
**Tests:** `tests/unit/test_repositories.py::TestReservationRepository::test_upsert_from_scraper`

### Task A4: ServiceRepository.bulk_upsert — normalizar fecha ISO
**Causa raíz:** `TypeError: SQLite DateTime type only accepts Python datetime` — el scraper entrega `"date": "2026-01-15T10:00:00"` (string) y se inserta directo.
**Fix:** parsear `svc["date"]` con `datetime.fromisoformat()` si es str antes de `Service(**svc)`.
**Files:** `src/otelms/domain/repositories/__init__.py` (~línea 522)
**Tests:** `tests/unit/test_repositories.py::TestServiceRepository::test_bulk_upsert`

### Task A5: PaymentRepository.bulk_upsert — normalizar fecha ISO (mismo fix)
**Files:** `src/otelms/domain/repositories/__init__.py` (~línea 568)
**Tests:** `tests/unit/test_repositories.py::TestPaymentRepository::test_bulk_upsert`

### Verificación Fase A: `pytest tests/unit/ -q` → **30 passed + 2 skipped + 0 failed**
Commit por tarea (o uno consolidado si son 5 fixes pequeños del mismo dominio).

---

## FASE B: Ruff 606 → 0

### Task B1: Auto-fix masivo de lo fixable
`uvx ruff check src/otelms --fix` — cubre UP045, W293, W292, I001, UP006, UP035, UP017, ERA001, E712 (≈390 errores)

### Task B2: F821 (8 undefined names) — revisar UNO a uno (posibles bugs reales)
### Task B3: PLC0415 (91 imports en funciones) — patrón INTENCIONAL en este repo (evita import circular en repositories/entities); mover a top-level solo donde sea seguro o agregar noqa con justificación; evaluar `per-file-ignores`
### Task B4: TRY003/TRY400/TRY300 (65) + PLR091 (24) + PLW060 (6) — revisar, arreglar o configurar ignore con justificación
### Task B5: actualizar pyproject: mover `select/ignore/per-file-ignores` a `[tool.ruff.lint]` (advertencia de deprecación)

### Verificación Fase B: `uvx ruff check src/otelms` → 0 errores

---

## FASE C: Mypy 263 → 0 (o config honesta)

### Task C1: name-defined (8) + import-not-found (2) + import-untyped (5) — bugs/imports reales, arreglar primero
### Task C2: attr-defined (43) + assignment (36) + union-attr (23) — tipados incorrectos, corregir modelos/entidades
### Task C3: no-untyped-def (58) + var-annotated (8) + no-any-return (11) — agregar anotaciones donde falta
### Task C4: arg-type (22) + return-value (14) + resto (~36) — corregir
### Task C5: si el volumen restante es inviable en una pasada: calibrar config (e.g. `disallow_untyped_defs` a false SOLO si no hay otra vía) y documentar decisión en el commit

### Verificación Fase C: `mypy src/otelms` → 0 errores (o config documentada + 0 errores)

---

## FASE D: Verificación integral + Docker

1. `pytest tests/unit/ -q` → 30 passed + 2 skipped + 0 failed
2. `uvx ruff check src/otelms` → limpio
3. `mypy src/otelms` → limpio
4. `git status` limpio; commits por fase
5. `docker compose build api worker beat` + `up -d` → 5/5 healthy; `curl /health`, `POST /hotels` OK

---

## Riesgos / Decisiones
- **PLC0415**: el patrón import-dentro-función es deliberado (dependencias circulares entities↔repositories). No romperlo a ciegas; noqa o per-file-ignores con comentario.
- **Mypy 263**: puede ser inviable llegar a 0 en una pasada sin riesgo; si al final quedan errores de "estilo de tipado" (no-untyped-def) se calibra config y se documenta — prioridad es que los errores de lógica (attr-defined, name-defined) queden en 0.
- **No tocar** el comportamiento de scraping Camoufox ni la lógica de negocio más allá de los fixes de los tests.
- **No commitear** sin que cada fase pase su verificación.
