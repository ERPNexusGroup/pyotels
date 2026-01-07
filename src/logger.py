import logging
import sys
import functools
import inspect
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from .config import config

def setup_logger(name: str = "otelms_scraper"):
    """
    Configura el logger principal con rotación diaria y salida a consola.
    """
    logger = logging.getLogger(name)
    
    # Evitar duplicar handlers si se llama varias veces
    if logger.hasHandlers():
        return logger

    # Nivel base
    level = logging.DEBUG if config.VERBOSE or config.DEBUG else logging.INFO
    logger.setLevel(level)

    # Formato
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. Handler de Archivo (Rotación diaria, max 10 archivos)
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
    file_handler.suffix = "%Y-%m-%d" # app.log.2023-10-27
    
    # 2. Handler de Consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Instancia global del logger
logger = setup_logger()

def log_execution(func):
    """
    Decorador para registrar la entrada, salida y argumentos de una función.
    Solo registra detalles si VERBOSE es True.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        module_name = func.__module__
        
        if config.VERBOSE:
            # Intentar obtener los nombres de los argumentos
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

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
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

            logger.debug(f"➡️  ENTRANDO (Async): {module_name}.{func_name}({args_str})")
        
        try:
            result = await func(*args, **kwargs)
            if config.VERBOSE:
                logger.debug(f"⬅️  SALIENDO (Async): {module_name}.{func_name} -> Retorno: {type(result).__name__}")
            return result
        except Exception as e:
            logger.error(f"❌ ERROR en {module_name}.{func_name}: {str(e)}", exc_info=True)
            raise e

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return wrapper

import asyncio
