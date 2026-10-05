"""Close/open dates en rooms vía OtelMS restrict_calendar endpoint.

NOTA: OtelMS usa room CATEGORIES (Matrimonial=13, Triple=15, etc.) no room numbers (305).
La habitación 305 pertenece a la categoría "Matrimonial".

Usage:
    from otelms.scraping.restrictions import close_dates, open_dates, get_categories

    await close_dates("18330", "2026-03-01", "2026-03-03", categories=["Matrimonial"])
    await open_dates("18330", "2026-03-01", "2026-03-03", categories=["Matrimonial"])

Cada función acepta un `client` ya autenticado; si no se pasa, se abre uno con
get_authenticated_http_session (login HTTP, sin browser). Inyectar el cliente es
lo que permite probar contra httpx.MockTransport sin tocar el portal.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date

import httpx
from bs4 import BeautifulSoup

from otelms.scraping.auth import get_authenticated_http_session

logger = logging.getLogger(__name__)

# Category name → ID mapping (from /reservation_c2/restrict_calendar)
CATEGORY_IDS: dict[str, str] = {
    "Matrimonial": "13",
    "Doble Individual": "14",
    "Triple": "15",
    "Quadruple": "16",
    "Quintuple": "17",
    "Sextuple": "18",
    "Suite Matrimonial": "19",
    "Suite Familiar": "20",
    "Overbooking": "21",
}

RESTRICT_URL = "/reservation_c2/save_restrict_close_open"
RESTRICT_CALENDAR_URL = "/reservation_c2/restrict_calendar"

# restrict_type: 0 = cerrar, 1 = abrir
RESTRICT_CLOSE = "0"
RESTRICT_OPEN = "1"

AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@asynccontextmanager
async def _client_for(
    hotel_id: str, client: httpx.AsyncClient | None
) -> AsyncIterator[httpx.AsyncClient]:
    """Usa el cliente inyectado o abre una sesión autenticada nueva."""
    if client is not None:
        yield client
        return
    async with await get_authenticated_http_session(hotel_id) as owned:
        yield owned


def _date_range(start_date: date | str, end_date: date | str) -> str:
    return f"{start_date} - {end_date}"


def _category_ids(categories: Sequence[str] | None) -> list[str]:
    return [CATEGORY_IDS[c] for c in (categories or [])] or list(CATEGORY_IDS.values())


async def _save_restrict(
    client: httpx.AsyncClient,
    restrict_type: str,
    date_str: str,
    categories: Sequence[str] | None,
) -> bool:
    """POST a save_restrict_close_open. True si el portal respondió HTTP 200."""
    resp = await client.post(
        RESTRICT_URL,
        data={
            "restrict_type": restrict_type,
            "date": date_str,
            "categories[]": _category_ids(categories),
        },
        headers=AJAX_HEADERS,
    )
    if resp.status_code == 200:
        return True
    logger.error(
        "Failed to %s dates: %s %s",
        "close" if restrict_type == RESTRICT_CLOSE else "open",
        resp.status_code,
        resp.text[:200],
    )
    return False


async def close_dates(
    hotel_id: str,
    start_date: date | str,
    end_date: date | str,
    categories: Sequence[str] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Cierra (bloquea) fechas para una o más categorías de habitación.

    Args:
        hotel_id: Hotel ID (18330).
        start_date: Fecha inicio (YYYY-MM-DD).
        end_date: Fecha fin (YYYY-MM-DD).
        categories: Lista de nombres de categorías. Si None, todas.
        client: Sesión HTTP ya autenticada. Si None, se abre una.

    Returns:
        True si el POST fue exitoso (HTTP 200).
    """
    date_str = _date_range(start_date, end_date)
    async with _client_for(hotel_id, client) as session:
        ok = await _save_restrict(session, RESTRICT_CLOSE, date_str, categories)
    if ok:
        logger.info("Closed dates %s for categories %s", date_str, categories or "all")
    return ok


async def open_dates(
    hotel_id: str,
    start_date: date | str,
    end_date: date | str,
    categories: Sequence[str] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Abre (desbloquea) fechas para una o más categorías de habitación."""
    date_str = _date_range(start_date, end_date)
    async with _client_for(hotel_id, client) as session:
        ok = await _save_restrict(session, RESTRICT_OPEN, date_str, categories)
    if ok:
        logger.info("Opened dates %s for categories %s", date_str, categories or "all")
    return ok


async def get_categories(
    hotel_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Obtiene la lista de categorías de habitación disponibles."""
    async with _client_for(hotel_id, client) as session:
        resp = await session.get(RESTRICT_CALENDAR_URL)
    soup = BeautifulSoup(resp.content, "html.parser")

    cat_select = soup.find("select", {"name": "categories[]"})
    if not cat_select:
        return []

    return [opt.get_text(strip=True) for opt in cat_select.find_all("option")]
