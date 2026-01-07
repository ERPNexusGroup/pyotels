# Configuración

`pyotels` utiliza `pydantic-settings` para gestionar la configuración a través de variables de entorno y archivos `.env`.

## Archivo .env

Crea un archivo llamado `.env` en la raíz del proyecto. Este archivo no debe ser compartido en el control de versiones si contiene credenciales sensibles.

### Variables Disponibles

| Variable | Tipo | Descripción | Valor por Defecto |
|----------|------|-------------|-------------------|
| `DEBUG` | bool | Activa el modo de depuración. | `True` |
| `DEBUG_REQUESTS` | bool | Logs detallados de peticiones HTTP. | `False` |
| `VERBOSE` | bool | Controla el nivel de detalle de los logs. | `False` |
| `LOG_LEVEL` | str | Nivel de log (INFO, DEBUG, ERROR). | `"INFO"` |
| `TARGET_DATE` | str | Fecha objetivo para el scraping (YYYY-MM-DD). | Fecha actual |
| `BASE_URL` | str | URL base de OtelMS. | `'otelms.com'` |

## Clase Config

La configuración se carga en la clase `Config` ubicada en `src/pyotels/config.py`.

```python
from pyotels.config import config

print(config.DEBUG)
print(config.TARGET_DATE)
```
