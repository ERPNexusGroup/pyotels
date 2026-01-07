# Referencia de API

Esta sección documentará las clases y funciones principales de la librería `pyotels`.

*(Esta sección está en construcción y se actualizará a medida que se desarrollen más módulos)*

## Módulos Principales

### `pyotels.config`

Contiene la configuración global de la aplicación.

- **Config**: Clase `BaseSettings` que carga variables de entorno.
    - `get_output_path(filename: str) -> str`: Retorna la ruta absoluta para guardar archivos.
    - `get_log_path() -> Path`: Retorna la ruta del directorio de logs.
