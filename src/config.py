import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuración de la aplicación."""
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore env vars not defined in the class
    )

    DEBUG: bool = True
    DEBUG_REQUESTS: bool = False

    VERBOSE: bool = False # Si es True, muestra logs detallados (DEBUG), si es False solo INFO/ERROR
    
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    LOG_LEVEL: Optional[str] = "INFO"
    LOG_BACKUP_COUNT: int = 10 # Cantidad de días/archivos a mantener

    # Configuración de la base de datos
    DATABASE_URL: str = "sqlite://otels.db"
    
    # Configuración del cache
    CACHE_TTL: int = 60 * 5

    # Configuración de Scraping
    # Por defecto extrae las reservas de la fecha actual
    TARGET_DATE: str = datetime.now().strftime('%Y-%m-%d')

    # Configuración Scrapy
    BASE_URL: str = 'otelms.com'

    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ACCEPT_REQUEST: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    def get_output_path(self, filename: str) -> str:
        """Genera la ruta absoluta para guardar archivos de salida."""
        output_dir = self.BASE_DIR / "output"
        output_dir.mkdir(exist_ok=True)
        return str(output_dir / filename)
    
    def get_log_path(self) -> Path:
        """Genera la ruta para el directorio de logs."""
        log_dir = self.BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        return log_dir

config = Config()
