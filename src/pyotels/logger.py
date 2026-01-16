import logging
import sys
import functools
import inspect
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
    level = logging.DEBUG if config.VERBOSE or config.DEBUG else logging.INFO
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

def log_execution(func):
    """
    Decorador para registrar ejecución.
    Intenta obtener el logger de la instancia (self.logger) si existe,
    de lo contrario usa el logger global.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        module_name = func.__module__
        
        # Intentar obtener logger de la instancia (self)
        current_logger = logger
        if args and hasattr(args[0], 'logger'):
            current_logger = args[0].logger
        
        if config.VERBOSE:
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                # Filtrar argumentos sensibles si fuera necesario
                args_str = ", ".join([f"{k}={repr(v)[:100]}" for k, v in bound_args.arguments.items()])
            except:
                args_str = "..."
            
            current_logger.debug(f"➡️  ENTRANDO: {func_name}({args_str})")
        
        try:
            result = func(*args, **kwargs)
            if config.VERBOSE:
                current_logger.debug(f"⬅️  SALIENDO: {func_name} -> Retorno: {type(result).__name__}")
            return result
        except Exception as e:
            current_logger.error(f"❌ ERROR en {func_name}: {str(e)}", exc_info=True)
            raise e

    return wrapper
