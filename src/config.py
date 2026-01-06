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
    BASE_DIR: Path = Path(__name__).parent

    LOG_LEVEL: Optional[str] = "INFO"

    # Configuración de la base de datos
    DATABASE_URL: str = "sqlite://otels.db"
    
    # Configuración del cache
    CACHE_TTL: int = 60 * 5  # 5 minutos

    # Configuración de Scraping
    # Por defecto extrae las reservas de la fecha actual
    TARGET_DATE: datetime = datetime.now().strftime('%Y-%m-%d')

    # Configuración Scrapy
    BASE_URL: str = 'otelms.com'

    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ACCEPT_REQUEST: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    @staticmethod
    def get_output_path(filename: str) -> str:
        if config.DEBUG:
            return os.path.join(config.DEV_OUTPUT_DIR, filename)
        return filename


config = Config()
