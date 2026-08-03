# Actualizar Credenciales de Hotel para Sincronización — Plan

> **Para Hermes:** Usar subagent-driven-development para ejecutar este plan tarea por tarea.

**Goal:** Permitir a Walter actualizar el username/password de un hotel (vía dashboard admin) y comenzar la sincronización de datos con las credenciales nuevas.

**Architecture:** El backend ya tiene el endpoint `PUT /admin/api/config/hotels/{hotel_id}` que acepta `username` y `password`, re-hashea (SHA-256) y re-encripta (Fernet). Solo falta: (1) cubrir el flujo con tests, (2) exponer la edición en la UI (modal en la pestaña Hoteles), (3) verificar que el sync usa las credenciales nuevas. No se toca el modelo ni la lógica de sync.

**Tech Stack:** FastAPI (Python 3.12), SQLAlchemy async, Pydantic v2, admin.html SPA vanilla JS, pytest, Fernet (crypto.py).

---

## Contexto actual (verificado)

| Pieza | Estado |
|---|---|
| `PUT /admin/api/config/hotels/{id}` | ✅ Existe, re-cifra password (config.py:257-263) |
| `HotelUpdate` schema | ✅ Tiene `username`, `password` opcionales |
| `SyncService.from_hotel()` | ✅ Desencripta `encrypted_password` (sync_service.py:101-106) |
| Pestaña Hoteles (admin.html) | ❌ Solo muestra username read-only, sin botón editar |
| Tests de hoteles | ❌ No cubren update de credenciales |
| Hotel de prueba | `118510 — Harmony Hotel Group Fixed`, sin rooms/categorías en DB local |

**Flujo deseado:** Dashboard → Configuración → Hoteles → botón "🔑 Credenciales" en la fila → modal con username + password → PUT → verificación (toast) → botón "Sync full" para probar con credenciales nuevas.

---

## Tarea 1: Test TDD del endpoint PUT de credenciales

**Objective:** Probar que `PUT /admin/api/config/hotels/{id}` actualiza username y password (hash + Fernet) correctamente.

**Files:**
- Test: `tests/unit/test_admin_crud.py` (agregar al final)

**Step 1: Escribir el test fallando**

```python
def test_hotel_update_credentials() -> None:
    """PUT /admin/api/config/hotels/{id} actualiza username y re-encripta password."""
    # TODO: usar TestClient + session de prueba; ver patrón de los tests existentes
    # (conftest/fixtures en tests/unit/) para obtener una sesión autenticada
    ...
    response = client.put(
        f"/admin/api/config/hotels/{hotel_id}",
        json={"username": "nuevo_user", "password": "nueva-pass-123"},
        headers={"X-API-Key": "..."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "nuevo_user"
    # verificar en DB que password_hash cambió y encrypted_password != anterior
```

**Step 2: Correr para verificar FAIL**

Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py -q`
Expected: FAIL (test no existe / no pasa)

**Step 3: Implementar el test completo** — inspeccionar primero el patrón de fixtures existente en `tests/unit/` (cómo crean client + hotel), luego escribir el test real con asserts de hash y Fernet.

**Step 4: Correr para verificar PASS**

Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/test_admin_crud.py -q`
Expected: 20 passed

**Step 5: Commit**

```bash
git -c user.name="Walter Cun" -c user.email="walte@local" commit -am "test(admin): cubrir update de credenciales de hotel"
```

---

## Tarea 2: Modal de credenciales en la pestaña Hoteles (frontend)

**Objective:** Añadir botón "🔑 Credenciales" por fila de hotel + modal con username/password que hace PUT a `/admin/api/config/hotels/{id}`.

**Files:**
- Modify: `src/otelms/api/static/admin.html` — `renderHotels()` (~línea 925), CSS modal ya existe (líneas 386-445, patrón `.modal-overlay/.modal-card`)

**Step 1: Agregar botón en la tabla de hoteles** (junto a Sync full / Calendario / Detalle):

```html
<button class="btn-ghost btn-small" data-creds="${esc(h.id)}">🔑 Credenciales</button>
```

**Step 2: Agregar handler en renderHotels()** que abre un modal con 2 campos:

```js
c.querySelectorAll("[data-creds]").forEach((btn) => {
  btn.addEventListener("click", () => openCredsModal(btn.dataset.creds, hotels));
});
```

**Step 3: Escribir `openCredsModal(hotelId, hotels)`** — función nueva:
1. Busca el hotel en la lista (para prellenar username)
2. Renderiza `.modal-overlay.show > .modal-card` con: título "Credenciales — {hotel.name}", input Usuario (prellenado), input Password (type=password, placeholder "•••••••• (dejar vacío = no cambiar)"), botones Cancelar / Guardar
3. Guardar → `PUT /admin/api/config/hotels/{id}` con `{ username, password? }` (solo incluir password si no está vacío) — usando el helper `api()` existente
4. Éxito → cerrar modal + toast + re-render `renderHotels()`

**Step 4: Verificar manual** — recargar `/admin`, Configuración → Hoteles, abrir modal, cambiar credenciales, guardar.

Run: servidor en `http://127.0.0.1:8010/admin` (proc_731111d9669c), login `changeme-secure-api-key-here`

**Step 5: Commit**

```bash
git -c user.name="Walter Cun" -c user.email="walte@local" commit -am "feat(admin): modal para editar credenciales del hotel"
```

---

## Tarea 3: Verificación del flujo completo sync

**Objective:** Probar end-to-end que con credenciales actualizadas el sync arranca (login al portal OtelMS).

**Files:**
- Ninguno (solo verificación)

**Step 1: Actualizar credenciales del hotel 118510 vía UI** (modal de la Tarea 2) con credenciales reales del portal.

**Step 2: Verificar en DB** que quedaron cifradas:

```bash
cd /d/Coders/00_activos/scraping_otelms_api
env -u PYTHONPATH .venv/Scripts/python.exe -c "
import asyncio
from otelms.domain.repositories.database import db
from otelms.domain.entities import Hotel

async def check():
    async with db.session() as s:
        h = await s.get(Hotel, '118510')
        print('username:', h.username)
        print('password_hash ok:', bool(h.password_hash))
        print('encrypted ok:', bool(h.encrypted_password))

asyncio.run(check())
"
```
Expected: username nuevo, ambos campos no vacíos.

**Step 3: Disparar sync** desde el dashboard (botón "Sync full") o API:

```bash
curl -s -X POST http://127.0.0.1:8010/admin/api/sync -H "Content-Type: application/json" -H "Authorization: Bearer <token>" -d '{"hotel_id":"118510","sync_type":"full"}'
```

**Step 4: Verificar resultado** — en el dashboard (Reportes / Sync Logs) o:
- `GET /admin/api/sync-logs?hotel_id=118510` → último log `status: completed` o ver el error real (login fallido → credenciales incorrectas)

**Step 5: Commit** (si hubo cambios de código durante la verificación)

---

## Riesgos y notas

- **No tocar** `password_hash` manualmente: el endpoint lo re-hashea solo. Editar DB directo rompe el login.
- **Password vacío en el modal** = no cambiar password (solo username). Incluirlo vacío haría hash de "" y rompería el login del scraper.
- El hotel 118510 local no tiene rooms/categorías — un sync "full" fallará o devolverá 0 si las credenciales del portal no son válidas; eso es esperado.
- Si el sync requiere dominio custom: revisar `custom_domain`/`use_custom_domain` en el modal si el portal del hotel no usa el dominio por defecto.
- **Login del admin** usa `X-API-Key` → JWT 12h; el header del modal usa el token JWT vía helper `api()`.

## Preguntas abiertas

1. ~~¿El hotel 118510 usa el dominio por defecto (`otelms.com`) o `custom_domain`?~~ **RESUELTO por Walter: dominio por defecto `otelms.com`** → el modal NO necesita campo de dominio.
2. ¿Quieres también un botón "Probar conexión" que haga login al portal y muestre OK/FAIL antes de guardar? (scope extra, YAGNI por defecto)
3. ¿Credenciales reales del portal para el hotel de prueba? (el admin no debe verlas; el modal guarda sin mostrar)
