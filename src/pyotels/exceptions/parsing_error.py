from pyotels.exceptions.base_error import OtelMSError


class ParsingError(OtelMSError):
    """Error al procesar el HTML (cambios en la estructura de la web)."""
    pass