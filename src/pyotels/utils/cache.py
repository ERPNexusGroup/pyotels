# src/pyotels/utils/cache.py
"""  """
from typing import Optional, Dict


def get_cache_key(url: str, params: Optional[Dict] = None) -> str:
    """Genera una clave única para la caché basada en URL y parámetros."""
    key_string = url
    if params:
        # Ordenar parámetros para consistencia en la clave
        sorted_params = tuple(sorted(params.items()))
        key_string += str(sorted_params)
    # Usar hash para asegurar longitud fija y caracteres válidos
    # return hashlib.sha256(key_string.encode()).hexdigest()
    return key_string
