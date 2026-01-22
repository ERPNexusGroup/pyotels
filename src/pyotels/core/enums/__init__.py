from enum import Enum


class StatusReservation(Enum):
    RESERVATION = 1
    CHECK_IN = 2
    CHECK_OUT = 3

    @classmethod
    def from_text(cls, text: str):
        mapping = {
            "Reserva": cls.RESERVATION,
            "Alojamiento": cls.CHECK_IN,
            "Salida": cls.CHECK_OUT,
        }
        return mapping.get(text, cls.RESERVATION)

    @classmethod
    def to_dict(cls):
        return {
            cls.RESERVATION: "Reservation",
            cls.CHECK_IN: "Check-in",
            cls.CHECK_OUT: "Check-out",
        }