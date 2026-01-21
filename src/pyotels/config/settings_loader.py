import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict


class SettingsLoader:
    SETTINGS_MODULE_ENV = "PYOTELS_SETTINGS_MODULE"
    ENV_NAME = "PYOTELS_ENV"

    @classmethod
    def load(cls) -> Dict[str, Any]:
        """
        Carga settings externos siguiendo una prioridad tipo Django.
        """
        data: Dict[str, Any] = {}

        # 1️⃣ Settings module explícito (tipo Django)
        module_path = os.getenv(cls.SETTINGS_MODULE_ENV)
        if module_path:
            data.update(cls._load_from_module_path(module_path))

        # 2️⃣ Settings por entorno
        env = os.getenv(cls.ENV_NAME)
        if env:
            data.update(cls._load_from_filename(f"settings_{env}.py"))

        # 3️⃣ Fallbacks automáticos
        data.update(cls._load_from_filename("settings.py"))
        data.update(cls._load_from_filename("config.py"))

        return data

    @staticmethod
    def _load_from_module_path(module_path: str) -> Dict[str, Any]:
        module = importlib.import_module(module_path)
        return SettingsLoader._extract_uppercase(module)

    @staticmethod
    def _load_from_filename(filename: str) -> Dict[str, Any]:
        path = Path(os.getcwd()) / filename
        if not path.exists():
            return {}

        spec = importlib.util.spec_from_file_location(filename, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[filename] = module
        spec.loader.exec_module(module)

        return SettingsLoader._extract_uppercase(module)

    @staticmethod
    def _extract_uppercase(module) -> Dict[str, Any]:
        """
        Extrae solo constantes tipo settings (MAYÚSCULAS).
        """
        return {
            key: value
            for key, value in vars(module).items()
            if key.isupper()
        }
