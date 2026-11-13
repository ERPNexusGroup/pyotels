"""Extraer room types + precios usando múltiples estrategias fallback."""
import re

# Estrategias para extraer room_type del calendar/folio
ROOM_TYPE_PATTERNS = [
    r"Habitaci[oó]n[:\s]*<br>[^<]*<br>\s*([A-Za-z\s]+)",           # HTML rendered: "Habitación:</b><br>106<br> Matrimonial"
    r"Habitaci[oó]n:\s*\d+\s+([A-Za-z]+)",                          # HTML: "Habitación: 106 Matrimonial"
    r"Tipo de habitaci[oó]n[^:]*:\s*.*?>([^<>]+)<",                  # HTML: "Tipo de habitación: <b>Matrimonial</b>"
    r"Tipo de habitaci[oó]n[^'\"]*:\s*\"([^\"]+)\"",                     # JS: "Tipo de habitación: \"Matrimonial\""
    r'"room_type"\s*:\s*"([^"]+)"',                                 # JS: "room_type": "Matrimonial"
    r'"room_category"\s*:\s*"([^"]+)"',                              # JS: "room_category": "..."
    r"category-heading.*?>([^<\n{]+?)<",                            # JS template
    r'"room_name"\s*:\s*"([^"]+)"',                                 # JS: "room_name": "Matrimonial"
    r"room_type[^,{]*:[\"']([^\"']+)[\"']",                          # Generic room_type
]


def extract_room_type(html_content: str) -> str | None:
    """Extrae el room_type usando múltiples estrategias."""
    for pattern in ROOM_TYPE_PATTERNS:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            room_type = match.group(1).strip()
            # Filter out non-room-type values
            if room_type and len(room_type) > 1 and room_type not in ("{", "}", ""):
                return room_type
    return None


def extract_room_number(html_content: str) -> str | None:
    """Extrae el room number (ej: '106', '201') del folio.

    Patrones:
    - HTML rendered: <b>Habitación:</b><br>106<br> Matrimonial
    - HTML: "Habitación: 106 Matrimonial"
    - JS: "data-title=\"Habitación: 106 Matrimonial\\r...\""
    """
    patterns = [
        r"Habitaci[oó]n[^0-9]{0,50}(\d+)",                     # HTML rendered: Habitación:</b><br>106<br>
        r"Habitaci[oó]n[:\s]*(\d+)",                            # HTML: "Habitación: 106 Matrimonial"
        r"Room[:\s]*(\d+)",
        r"room_number[\"'\s]*[=:] [\"'\s]*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_room_prices(html_content: str) -> list[dict]:
    """Extrae precios de habitación desde el folio.

    Busca en room charges: fechas + descripciones + imports.
    Filtra valores que no son precios reales (IDs, timestamps).
    """
    prices = []

    rows = re.findall(
        r"<tr[^>]*>(.*?)</tr>", html_content, re.DOTALL | re.IGNORECASE
    )
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        if len(cells) >= 3:
            price_str = cells[-1].strip()
            price_match = re.search(r"[\d.,]+", price_str)
            if price_match:
                price_str = price_match.group(0).replace(",", ".")
                try:
                    price_val = float(price_str)
                    # Filter: realistic room prices (10.00 - 9999.99)
                    if 10 <= price_val <= 9999.99:
                        prices.append({
                            "price": price_val,
                            "description": cells[-2].strip()[:50] if len(cells) >= 2 else "",
                            "date": cells[0].strip()[:20] if cells else "",
                        })
                except ValueError:
                    pass
    return prices


def extract_all_rooms_from_calendar(html_content: str) -> list[dict]:
    """Extrae todas las room categories + capacidad del calendar sidebar.

    Patrón: <div class="calendar_rooms_dott">Matrimonial 102</div>
    """
    rooms = []
    room_divs = re.findall(
        r'<div class="calendar_rooms_dott">\s*([^<]+?)\s*</div>', html_content
    )
    for raw_name in room_divs:
        name = raw_name.strip()
        if not name or len(name) < 2:
            continue
        capacity_match = re.search(r'(\d+)\s*$', name)
        capacity = int(capacity_match.group(1)) if capacity_match else 2
        clean_name = re.sub(r'\s*\d+\s*$', '', name)
        rooms.append({
            "room_type": clean_name,
            "category_id": clean_name.lower().replace(" ", "_"),
            "capacity": capacity,
        })
    return rooms
