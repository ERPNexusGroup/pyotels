# scraping_otelms_api (pyotels)

Scraper/API de OtelMS del Harmony Hotel Group. Repo remoto: `github.com/ERPNexusGroup/pyotels` (rama main).

## Datos del sistema OtelMS (operativos)

- URL login: `https://desktop.otelms.com/login_c2/single_login?hmsid={id}`
- Hotel ID: **18330**
- Ver `.env` local (nunca versionar credenciales; `.env.example` es la plantilla).

## Entorno

- Venv propio → `env -u PYTHONPATH .venv/Scripts/python.exe` (PYTHONPATH de Hermes rompe imports).
- Alembic para migraciones; Docker en `docker/` para servicios dependientes.

## Git

- Commits: `git -c user.name="Walter Cun" -c user.email="walte@local" commit`.

## Estado

- EN EJECUCIÓN. (Actualizar al abrir/cerrar.)