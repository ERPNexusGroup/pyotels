class OtelMSError(Exception):
    """Excepción base para la librería PyOtels."""
    pass

class AuthenticationError(OtelMSError):
    """Fallo en el inicio de sesión (credenciales inválidas)."""
    pass

class NetworkError(OtelMSError):
    """Problemas de conexión o timeouts."""
    pass

class ParsingError(OtelMSError):
    """Error al procesar el HTML (cambios en la estructura de la web)."""
    pass

class DataNotFoundError(OtelMSError):
    """El recurso solicitado (reserva, habitación) no existe."""
    pass
