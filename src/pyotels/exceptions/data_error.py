from pyotels.exceptions.base_error import OtelMSError


class DataNotFoundError(OtelMSError):
    """El recurso solicitado (reserva, habitación) no existe."""
    pass
