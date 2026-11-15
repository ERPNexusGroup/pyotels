"""
Configuración de logging estructurado con structlog.
"""
import logging
from logging.handlers import RotatingFileHandler
import re
import sys
from typing import Any, cast

import structlog
from structlog.types import EventDict, WrappedLogger

from otelms.config.settings import settings

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _PlainFileFormatter(logging.Formatter):
    """Formatea logs de archivo eliminando códigos ANSI de consola."""

    def format(self, record: logging.LogRecord) -> str:
        return _ANSI_RE.sub("", super().format(record))


def add_app_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Añade contexto de la aplicación a todos los logs."""
    event_dict["app"] = "otelms-api"
    event_dict["env"] = settings.app_env
    return event_dict


def add_correlation_id(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Añade correlation_id si existe en el contexto."""
    # structlog.contextvars usa contextvars automáticamente
    return event_dict


def setup_logging() -> None:
    """Configura structlog para toda la aplicación."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configurar logging estándar
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Silenciar loggers ruidosos de terceros
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("camoufox").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)

    # Procesadores compartidos
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        add_app_context,
        add_correlation_id,
    ]

    if settings.log_format == "json":
        # Formato JSON para producción / agregadores de logs
        processors = shared_processors + [
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Formato consola legible para desarrollo
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configurar file handler rotativo si se especifica (sin duplicar handlers)
    if settings.log_file:
        log_path = settings.get_log_path()
        root_logger = logging.getLogger()
        already_attached = any(
            isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_path)
            for h in root_logger.handlers
        )
        if not already_attached:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(_PlainFileFormatter("%(message)s"))
            root_logger.addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Obtiene un logger configurado."""
    # structlog tipa get_logger como BoundLogger genérico; el wrapper_class
    # configurado arriba es stdlib.BoundLogger, así que el cast es seguro.
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
