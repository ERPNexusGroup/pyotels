"""
Restriction endpoints (fechas cerradas por categoría y tarifa).

A diferencia de disponibilidad, aquí **no hay tabla**: las restricciones se
leen del portal cada vez que se piden. Motivo: son pocas y muy cambiantes
(alguien abre un día desde la recepción y cambia al momento), y el estado
vive en la rejilla, no en el booking. Persistirlo daría una foto congelada
justo de lo que más importa ver al día.

Consecuencia práctica: esta ruta golpea OtelMS. No es una lectura de la base
de datos local como el resto del API, así que es más lenta y cuenta como un
scrapeo.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from otelms.api.dependencies import (
    get_cache,
    get_category_repo,
    live_rate_limit,
    verify_api_key,
)
from otelms.api.schemas import RestrictionResponse, RestrictionRow
from otelms.domain.repositories import CategoryRepository
from otelms.scraping.restrictions import (
    CATEGORY_IDS,
    RATE_STANDARD,
    get_restrictions,
)
from otelms.utils.logging import get_logger

router = APIRouter(
    prefix="/restrictions",
    tags=["restrictions"],
    dependencies=[Depends(verify_api_key)],
)
logger = get_logger(__name__)

# La rejilla del portal muestra 46 días. Es lo que hay; pedir más no acorta la
# ventana ni da error, simplemente no devuelve celdas de más.
MAX_RANGE_DAYS = 46


@router.get(
    "",
    response_model=RestrictionResponse,
    dependencies=[Depends(live_rate_limit("restrictions.list"))],
)
async def list_restrictions(
    hotel_id: str = Query(..., description="Hotel ID"),
    date_from: date = Query(
        default_factory=date.today, description="Fecha inicial (YYYY-MM-DD)"
    ),
    date_to: date = Query(
        default_factory=lambda: date.today() + timedelta(days=MAX_RANGE_DAYS),
        description="Fecha final (YYYY-MM-DD)",
    ),
    category_id: str | None = Query(None, description="Filtra por categoría"),
    rate_id: str = Query(RATE_STANDARD, description="1 = Standard, 2 = Feriados"),
    cat_repo: CategoryRepository = Depends(get_category_repo),
) -> RestrictionResponse:
    """Fechas cerradas, leídas en vivo de la rejilla de OtelMS.

    Devuelve únicamente las celdas **cerradas**. Una categoría sin ninguna
    celda cerrada en el rango no aparece, así que la ausencia de un
    `{category_id, date}` significa "abierta", no "sin datos".
    """
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be greater than or equal to date_from",
        )

    cache = await get_cache()
    cache_key = (
        f"live:restrictions:{hotel_id}:{date_from.isoformat()}:{date_to.isoformat()}:"
        f"{category_id or ''}:{rate_id}"
    )
    cached = await cache.get(cache_key)
    if cached is not None:
        return RestrictionResponse.model_validate(cached)

    category_ids = [category_id] if category_id else None
    cells = await get_restrictions(
        hotel_id,
        category_ids=category_ids,
        rate_id=rate_id,
        date_from=date_from,
        date_to=date_to,
    )

    categories = await cat_repo.get_with_rooms(hotel_id)
    names = {c.id: c.name for c in categories}
    # Sin sync de categorías todavía, el mapeo del portal hace de nombre.
    for portal_id, category_name in CATEGORY_IDS.items():
        names.setdefault(portal_id, category_name)

    rows = [
        RestrictionRow(
            category_id=cell["category_id"],
            category_name=names.get(cell["category_id"]),
            rate_id=cell["rate_id"],
            date=date.fromisoformat(cell["date"]),
            closed=cell["closed"],
        )
        for cell in cells
    ]
    # El orden lo pone el HTML de la rejilla, que puede cambiar con cualquier
    # retoque del portal. Ordenar aquí para que el cliente pueda comparar
    # respuesta contra respuesta sin tener que ordenar por su cuenta.
    rows.sort(key=lambda row: (row.date, row.category_id))

    logger.info(
        "Restrictions listed for %s..%s: %d closed cells",
        date_from, date_to, len(rows),
    )
    resp = RestrictionResponse(
        hotel_id=hotel_id,
        date_from=date_from,
        date_to=date_to,
        source="otelms/restrict_calendar",
        count=len(rows),
        items=rows,
    )
    await cache.set(cache_key, resp.model_dump(mode="json"), ttl=60)
    return resp
