# Instalación

## Prerrequisitos

Asegúrate de tener instalado Python 3.12 o superior en tu sistema.

## Pasos de Instalación

1. **Clonar el repositorio**

   ```bash
   git clone <url-del-repositorio>
   cd scraping_otelms_api
   ```

2. **Crear un entorno virtual**

   Se recomienda utilizar un entorno virtual para aislar las dependencias del proyecto.

   ```bash
   python -m venv .venv
   ```

   Activa el entorno virtual:
   - En Windows: `.venv\Scripts\activate`
   - En macOS/Linux: `source .venv/bin/activate`

3. **Instalar dependencias**

   Instala el paquete en modo editable junto con sus dependencias:

   ```bash
   pip install -e .
   ```

   Esto instalará las librerías necesarias como `beautifulsoup4`, `requests`, `tortoise-orm`, etc.
