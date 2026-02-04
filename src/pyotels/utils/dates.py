# utils/dates.py
from datetime import datetime, timezone

SECONDS_IN_DAY = 60 * 60 * 24

def date_to_day_id(date_str: str) -> int:
    """
    Convierte una fecha YYYY-MM-DD a day_id (días unix)
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() // SECONDS_IN_DAY)


def day_id_to_date(day_id: int) -> str:
    """
    Debug / logging
    """
    return datetime.utcfromtimestamp(day_id * SECONDS_IN_DAY).strftime("%Y-%m-%d")
