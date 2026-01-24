import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Union

from ..config.settings import config


class SafeFormatter(logging.Formatter):
    """
    Formatter que garantiza que todos los campos esperados
    existan en el LogRecord.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "classname"):
            record.classname = "OtelsLogger"
        return super().format(record)


class ColoredFormatter(SafeFormatter):
    """
    Formatter para agregar colores a los logs en la terminal.
    Solo debe usarse en consola (nunca en archivo).
    """

    COLORS = {
        'DEBUG': '\033[94m',  # Azul
        'INFO': '\033[92m',  # Verde
        'WARNING': '\033[93m',  # Amarillo
        'ERROR': '\033[91m',  # Rojo
        'CRITICAL': '\033[95m',  # Magenta
        'ENDC': '\033[0m',  # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = self.COLORS.get(record.levelname, self.COLORS['ENDC'])
        return f"{color}{message}{self.COLORS['ENDC']}"


class ClassLoggerAdapter(logging.LoggerAdapter):
    """
    Adaptador que inyecta el nombre de la clase en los logs
    sin ensuciar el mensaje original.
    """

    def process(self, msg, kwargs):
        kwargs.setdefault("extra", {})
        kwargs["extra"]["classname"] = self.extra.get("classname", "N/A")
        return msg, kwargs


def get_logger(
        name: str = "otelms_scraper",
        classname: Optional[str] = None
) -> Union[logging.Logger, logging.LoggerAdapter]:
    """
    Factory de logger.

    - Configura el logger una sola vez
    - Retorna LoggerAdapter si se pasa classname
    """
    logger = logging.getLogger(name)

    if not getattr(logger, "_configured", False):
        _configure_logger(logger)
        logger._configured = True  # type: ignore[attr-defined]

    if classname:
        return ClassLoggerAdapter(logger, {"classname": classname})

    return logger


def _configure_logger(logger: logging.Logger) -> None:
    log_level = logging.DEBUG if config.DEBUG else logging.INFO
    logger.setLevel(log_level)
    logger.propagate = False

    base_formatter = SafeFormatter(
        '[%(asctime)s] [%(levelname)s] [%(classname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_handler = logging.StreamHandler(sys.stdout)

    if (config.DEBUG and sys.stdout.isatty()) or config.FORCE_COLOR:
        console_formatter = ColoredFormatter(
            '[%(asctime)s] [%(levelname)s] [%(classname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
    else:
        console_handler.setFormatter(base_formatter)

    logger.addHandler(console_handler)

    try:
        log_dir = config.get_log_path()
        log_file = log_dir / "app.log"

        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
            utc=True,
        )

        file_handler.setFormatter(base_formatter)
        file_handler.suffix = "%Y-%m-%d"
        logger.addHandler(file_handler)

    except (PermissionError, OSError) as exc:
        print(f"⚠️ No se pudo configurar el log a archivo: {exc}", file=sys.stderr)


# Logger por defecto para compatibilidad
logger = get_logger()
