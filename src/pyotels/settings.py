from typing import Any, Optional

from .config import Config
from .settings_loader import SettingsLoader


class Settings:
    """
    Proxy de configuración estilo Django.

    - Defaults desde Config (Pydantic)
    - Overrides automáticos desde settings del proyecto
    - Override manual vía configure()
    """

    _config_object: Optional[Config] = None

    def _get_config(self) -> Config:
        if self._config_object is None:
            # Defaults
            base_data = Config().model_dump()

            # Overrides externos
            external_data = SettingsLoader.load()
            base_data.update(external_data)

            self._config_object = Config(**base_data)

        return self._config_object

    def configure(self, **kwargs: Any) -> None:
        """
        Override manual en runtime (máxima prioridad).
        """
        current = self._get_config().model_dump()
        current.update(kwargs)
        self._config_object = Config(**current)

    def dump(self) -> dict:
        """
        Debug: devuelve todos los settings actuales.
        """
        return self._get_config().model_dump()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_config(), name)


# Instancia singleton
settings = Settings()

# Alias para compatibilidad
config = settings
