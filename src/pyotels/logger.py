import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from .settings import config

class ColoredFormatter(logging.Formatter):
    """
    Formatter para agregar colores a los logs en la terminal.
    """
    COLORS = {
        'DEBUG': '\033[94m',    # Azul
        'INFO': '\033[92m',     # Verde
        'WARNING': '\033[93m',  # Amarillo
        'ERROR': '\033[91m',    # Rojo
        'CRITICAL': '\033[95m', # Magenta
        'ENDC': '\033[0m'       # Reset
    }

    def format(self, record):
        log_message = super().format(record)
        return f"{self.COLORS.get(record.levelname, self.COLORS['ENDC'])}{log_message}{self.COLORS['ENDC']}"

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

    # Formatter base para el archivo de log
    base_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. Handler de Consola
    console_handler = logging.StreamHandler(sys.stdout)
    if config.DEBUG:
        # Usar formatter con colores si DEBUG está activo
        console_formatter = ColoredFormatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
    else:
        console_handler.setFormatter(base_formatter)
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
        # El archivo de log no debe tener códigos de color
        file_handler.setFormatter(base_formatter)
        file_handler.suffix = "%Y-%m-%d"
        logger.addHandler(file_handler)
    except (PermissionError, OSError) as e:
        sys.stderr.write(f"⚠️ No se pudo configurar log a archivo: {e}\n")

# Instancia global por defecto para compatibilidad
logger = get_logger()
