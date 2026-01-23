import re
from typing import Optional, Union


def normalize_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    # Extrae el primer número válido (positivo o negativo)
    match = re.search(r'-?\d+(?:[\.,]\d+)?', value)
    if not match:
        return None

    number = match.group(0).replace(',', '.')
    try:
        return float(number)
    except ValueError:
        return None


from datetime import datetime

DATE_PATTERNS = [
    "%Y-%m-%d"
]


def normalize_date(value: Optional[str],
                   *,
                   with_time: bool = False,
                   only_time: bool = False,
                   output_format: str = "%Y-%m-%d %H:%M",
                   default_time: str = "00:00",
                   return_datetime: bool = False) -> Optional[Union[str, datetime]]:
    if not value:
        return None

    text = str(value)

    # 1️⃣ Extrae fecha (YYYY-MM-DD)
    date_match = re.search(r'\d{4}-\d{2}-\d{2}', text)
    if not date_match:
        return None

    date_part = date_match.group()

    # 2️⃣ Extrae hora (HH:MM) si existe
    time_match = re.search(r'\d{2}:\d{2}', text)
    time_part = time_match.group() if time_match else default_time

    # 3️⃣ Construye datetime base
    dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")

    # 4️⃣ Lógica de salida
    if only_time:
        result = dt.strftime("%H:%M")
    elif with_time:
        result = dt.strftime(output_format)
    else:
        result = dt.strftime("%Y-%m-%d")

    return dt if return_datetime else result


# if __name__ == '__main__':
#     print(normalize_date("Jueves - 2026-02-05 14:00"))
#     print(normalize_date("2026-01-23", with_time=True))
#     print(normalize_date("Sábado - 2026-02-07 12:00", with_time=False))
#     print(normalize_date("Domingo - 2026-02-08 12:00", only_time=True))
#     print(normalize_date(
#         "Reserva creada el Domingo - 2026-02-08 12:00",
#         output_format="%d/%m/%Y %H:%M"
#     ))
#     print(normalize_date(
#         "Texto random 2026-02-05 14:00 bla bla",
#         return_datetime=True
#     ))
