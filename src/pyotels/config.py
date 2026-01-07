import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuración base de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Cambiá a "forbid" si querés modo estricto
    )

    # -----------------------
    # Flags generales
    # -----------------------
    DEBUG: bool = True
    DEBUG_REQUESTS: bool = False
    VERBOSE: bool = False

    LOG_LEVEL: Optional[str] = "INFO"
    LOG_BACKUP_COUNT: int = 10

    # -----------------------
    # Paths
    # -----------------------
    BASE_DIR: Path = Path(os.getcwd())

    # -----------------------
    # Scraping / negocio
    # -----------------------
    TARGET_DATE: str = datetime.now().strftime("%Y-%m-%d")
    BASE_URL: str = "otelms.com"

    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    ACCEPT_REQUEST: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    # -----------------------
    # Helpers
    # -----------------------
    def get_output_path(self, filename: str) -> str:
        output_dir = self.BASE_DIR / "output"
        output_dir.mkdir(exist_ok=True)
        return str(output_dir / filename)

    def get_log_path(self) -> Path:
        log_dir = self.BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        return log_dir
