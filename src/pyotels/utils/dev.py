# src/pyotels/utils/dev.py
"""  """
from pyotels.utils.logger import logger
from ..config.settings import config


def save_html_debug(html_content: str, filename: str):
    """
    Guarda el contenido HTML en disco si DEBUG está activo.
    Limpia líneas vacías y espacios innecesarios para facilitar la lectura.
    """
    if config.DEBUG:
        try:
            html_dir = config.get_html_path()
            html_dir.mkdir(exist_ok=True)
            file_path = html_dir / filename

            # 1. Eliminar líneas vacías y espacios extra al inicio/final de cada línea
            lines = [line.strip() for line in html_content.splitlines()]
            non_empty_lines = [line for line in lines if line]

            # 2. Unir de nuevo
            cleaned_content = "\n".join(non_empty_lines)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)

            logger.debug(f"HTML guardado en disco: {file_path}")
        except Exception as e:
            logger.error(f"Error guardando HTML en disco: {e}")
