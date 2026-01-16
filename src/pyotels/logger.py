import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from .settings import config

class ClassLoggerAdapter(logging.LoggerAdapter):
    """
    Adaptador para inyectar el nombre de la clase en los logs.
    """
    def process(self, msg, kwargs):
        return f"[{self.extra['classname']}] {msg}", kwargs

def get_logger(name: str = "otelms_scraper", classname: str = None):
    """
    Obtiene un logger configurado. Si se proporciona classname, devuelve un adaptador
    que prefija el nombre de la clase en los mensajes.
    """
    logger = logging.getLogger(name)
    
    if not logger.hasHandlers():
        _configure_logger(logger)
        
    if classname:
        return ClassLoggerAdapter(logger, {'classname': classname})
    
    return logger

def _configure_logger(logger):
    """Configuración interna del logger."""
    level = logging.DEBUG if config.DEBUG else logging.INFO
    logger.setLevel(level)

    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. Handler de Consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. Handler de Archivo
    try:
        log_dir = config.get_log_path()
        log_file = log_dir / "app.log"

        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"
        logger.addHandler(file_handler)
    except (PermissionError, OSError) as e:
        sys.stderr.write(f"⚠️ No se pudo configurar log a archivo: {e}\n")

# Instancia global por defecto para compatibilidad
logger = get_logger()

