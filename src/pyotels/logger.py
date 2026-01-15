import logging
import sys
import functools
import inspect
from logging.handlers import TimedRotatingFileHandler
from .settings import config

def setup_logger(name: str = "otelms_scraper"):
    """
    Configura el logger principal.
    """
    logger = logging.getLogger(name)
    
    if logger.hasHandlers():
        return logger

    level = logging.DEBUG if config.VERBOSE or config.DEBUG else logging.INFO
    logger.setLevel(level)

    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. Handler de Consola (Siempre activo)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. Handler de Archivo (Opcional y seguro)
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
        # Si falla (ej. entorno serverless o sin permisos), solo avisamos por consola
        sys.stderr.write(f"⚠️ No se pudo configurar log a archivo: {e}\n")

    return logger

logger = setup_logger()

def log_execution(func):
    """
    Decorador para registrar ejecución.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        module_name = func.__module__
        
        if config.VERBOSE:
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                args_str = ", ".join([f"{k}={repr(v)[:100]}" for k, v in bound_args.arguments.items()])
            except:
                args_str = "..."
            
            logger.debug(f"➡️  ENTRANDO: {module_name}.{func_name}({args_str})")
        
        try:
            result = func(*args, **kwargs)
            if config.VERBOSE:
                logger.debug(f"⬅️  SALIENDO: {module_name}.{func_name} -> Retorno: {type(result).__name__}")
            return result
        except Exception as e:
            logger.error(f"❌ ERROR en {module_name}.{func_name}: {str(e)}", exc_info=True)
            raise e

    return wrapper
