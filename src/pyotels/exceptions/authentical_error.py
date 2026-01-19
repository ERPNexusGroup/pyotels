from pyotels.exceptions.base_error import OtelMSError


class AuthenticationError(OtelMSError):
    """Fallo en el inicio de sesión (credenciales inválidas)."""
    pass
