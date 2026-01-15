# src/pyotels/utils/dev.py
"""  """
from ..logger import logger, log_execution
from ..settings import config


def save_html_debug(html_content: str, filename: str):
    """Guarda el contenido HTML crudo en disco si DEBUG está activo."""
    if config.DEBUG:
        try:
            html_dir = config.BASE_DIR / "html"
            html_dir.mkdir(exist_ok=True)
            file_path = html_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.debug(f"HTML guardado en disco: {file_path}")
        except Exception as e:
            logger.error(f"Error guardando HTML en disco: {e}")
