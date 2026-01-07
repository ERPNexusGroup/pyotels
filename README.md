# pyotels

**Librería para scraping de OtelMS.**

`pyotels` es una herramienta diseñada para facilitar la extracción de datos (scraping) desde la plataforma OtelMS. Permite gestionar reservas, consultar disponibilidad y extraer información relevante de manera automatizada, integrándose con bases de datos y sistemas de caché.

## 🚀 Características

- **Scraping Automatizado**: Extracción de reservas y disponibilidad.
- **Configuración Flexible**: Gestión mediante variables de entorno y `pydantic-settings`.
- **Persistencia**: Soporte para bases de datos mediante Tortoise ORM (PostgreSQL, SQLite, etc.).
- **Alto Rendimiento**: Uso de `aiocache` y operaciones asíncronas.
- **Logging**: Sistema de logs configurable para depuración y monitoreo.

## 📋 Requisitos

- Python >= 3.12
- Dependencias listadas en `pyproject.toml` (beautifulsoup4, requests, tortoise-orm, etc.)

## 🛠️ Instalación

1.  Clona el repositorio:
    ```bash
    git clone <url-del-repositorio>
    cd scraping_otelms_api
    ```

2.  Crea un entorno virtual e instala las dependencias:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # En Windows: .venv\Scripts\activate
    pip install -e .
    ```

## ⚙️ Configuración

Crea un archivo `.env` en la raíz del proyecto para configurar las variables de entorno. Puedes consultar `src/pyotels/config.py` para ver todas las opciones disponibles.

Ejemplo de `.env`:

```ini
DEBUG=True
LOG_LEVEL=INFO
TARGET_DATE=2023-10-27
```

## 📖 Ejemplos de Uso

```python
from pyotels.config import config

def main():
    print(f"Iniciando scraping en {config.BASE_URL}")
    print(f"Fecha objetivo: {config.TARGET_DATE}")
    
    # Lógica de scraping aquí...

if __name__ == "__main__":
    main()
```

Para más detalles, consulta la documentación en la carpeta `/docs`.

## 🗺️ Roadmap

- [x] Estructura inicial del proyecto y configuración.
- [x] Implementación del login y manejo de sesiones en OtelMS.
- [ ] Extracción de detalles de reservas (Guest, Room, Price).
- [ ] Almacenamiento de datos en base de datos relacional.
- [ ] Generación de reportes automáticos.

## 👥 Colaboradores y Creadores

Este proyecto ha sido desarrollado con el objetivo de automatizar procesos en OtelMS.

- **Creador**: [Tu Nombre]
- **Colaboradores**: ¡Bienvenidas las PRs!

## 📄 Licencia

Este proyecto está bajo la licencia [MIT](https://opensource.org/licenses/MIT]. Consulta el archivo `LICENSE` para más detalles.
