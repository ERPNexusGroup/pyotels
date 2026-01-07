# Uso Básico

Esta sección describe cómo empezar a utilizar `pyotels` para realizar tareas comunes.

## Ejecución de Scripts

El proyecto incluye herramientas auxiliares en la carpeta `ia_tools` que pueden servir como punto de partida o para verificación.

Por ejemplo, para verificar detalles locales:

```bash
python ia_tools/verify_details.py
```

## Ejemplo de Código

A continuación se muestra un ejemplo simple de cómo se podría estructurar un script de scraping utilizando la configuración del proyecto.

```python
import asyncio
from pyotels.config import config

async def main():
    print(f"Conectando a {config.BASE_URL}...")
    # Aquí iría la lógica de inicialización de clientes HTTP, conexión a DB, etc.
    
    if config.DEBUG:
        print("Modo DEBUG activado")

if __name__ == "__main__":
    asyncio.run(main())
```

## Logs

Los logs se almacenan en la carpeta `logs/` definida en la configuración. Asegúrate de revisar `app.log` para ver la salida de la ejecución y posibles errores.
